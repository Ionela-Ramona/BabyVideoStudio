# Plan animație – Fetița merge la Mama și se îmbrățișează

10 s, 30 fps, 300 cadre, Blender 4.5 headless. Keyframe din Python pe rig-urile din CONTRACT. Doar plan; animația începe după aprobarea imaginii statice.

## 0. Convenții
- Orientare: mama stă la x=+0.5, privește spre −X (`rotation_euler.z = -90°`); fetița privește spre +X (`+90°`). Coordonatorul poate alege ±70–80° ca să se vadă fețele din cameră.
- Toate valorile de mai jos sunt de pornit; se reglează după randări de test. Unghiurile sunt în grade, în spațiul local al oaselor.
- Totul se animă cu keyframe-uri pe `pose.bones[...]`, `rig.location`, `foot_ik`/`hand_ik`, `privire`, shape keys. Fără NLA, fără deformări, doar piese rigide.

## 1. Timeline (cadre)
| Cadre | Fetița | Mama | Privire / față |
|---|---|---|---|
| 0–20 | idle: respirație, ușor leagăn, brațele relaxate | idle: respirație, schimb de greutate, mâinile în față | privirile spre camera/orizont, blink |
| 12–30 | anticipație: greutate pe piciorul de sprijin, cap spre mamă, primul pas | observă fetița: cap se întoarce (cadrele 20–40) | fetița: privire spre fața mamei (de la cad. 20) |
| 30–110 | mers, croazieră (~7 pași) | idle activ, se pregătește (umeri coboară, ușor surâs) | mama: privire spre fetiță de la cad. 40 |
| 105–140 | decelerare: ultimii 3 pași mai scurți, se oprește la x≈-0.1 | **începe aplecarea la cad. 100** (suprapus, nu așteaptă oprirea) | contact vizual de la cad. 125 |
| 100–165 | settle: se echilibrează, brațele ridică ușor | aplecare completă la cad. 165 (genunchi, șold înapoi, coloană înainte) | zâmbet crește 130–150 |
| 150–200 | ridică brațele spre mamă (160–195), ușor pe vârfuri | brațele se deschid (150–175), apoi se închid (175–205) | zâmbet maxim 150+ |
| 200–285 | îmbrățișare: brațele în jurul gâtului/umerilor mamei, cap înclinat, leagăn mic | îmbrățișare: ținere, balans lent stânga-dreapta ±1.5° | ochii pe jumătate închiși ~cad. 230 (opțional), blink după 250 |
| 285–300 | respirație, cap pe umăr | respirație, ușor relaxare | menținere, fără îngheț (zgomot activ) |

Principii: acțiunile se suprapun (mama începe aplecarea înainte ca fetița să se oprească; fetița ridică brațele înainte ca mama să se fi oprit din coborâre). Fiecare mișcare are anticipare (mică mișcare în sens opus), ease in/out, follow-through (cap/brațe ajung din urmă cu 2–4 cadre) și settle (ușor overshoot de 5–10%, revenire în 6–8 cadre).

## 2. Mersul fetiței (toddler)
- Distanță: x −2.2 → −0.1 = 2.1 m. Lungime pas ≈ 0.21 m, cadență ≈ 2.7 pași/s → **11 cadre/pas** (22 cadre/ciclu complet). ~10 pași în ~110 cadre (cad. 30–140).
- Profil de viteză: primii 2 pași = 0.12, 0.17 m; croazieră 0.22; ultimii 3 pași 0.18, 0.12, 0.07 m (cadența scade ușor: 11→13 cadre/pas). Ultimul picior se aduce lângă celălalt (cad. ~140).
- Mers de copil: baza lată (picioare ±0.07 m pe Y față de linia de mers), genunchi ușor îndoiți, trunchi drept, balans lateral al șoldurilor ±3° (rotație Z pe `hips`) și înclinare ±2° pe X, rotație a trunchiului ±4° contra șoldurilor, brațe ușor în afară/ridicate (abducție ~25°, antebrațe îndoite ~30°) cu balans mic, cap stabil (compensează ±50% din mișcarea trunchiului).
- Fără alunecare: `foot_ik` are keyframe în trei stări per pas: **plantat** (poziție world fixă, constantă pe tot intervalul de sprijin ~60% din ciclu, interpolare CONSTANT între chei identice), **ridicat** (arc: z +0.04 m la mijloc, înaintare 2×pas), **plantat nou**. Poziția `foot_ik` plantată se calculează în world-space din traseul rădăcinii.
- Rădăcina: `rig.location.x` urmează o curbă monotonă; centrul de greutate (`hips` z) oscilează ±8 mm pe pas (mai jos la dublu sprijin). Pentru no-slide: x_rădăcină = media pozițiilor celor două tălpi plantate, interpolat smooth; se calculează tălpile din lista de pași, nu invers.
- Rotația piciorului: călcâi atinge primul, tălpile rămân pe podea (z=0) cât timp plantate.

## 3. Aplecarea mamei
- Țintă: mama (1.65 m) ajunge cu capul la ~1.15 m, chest aproape de nivelul capului fetiței (0.95 m).
- Ordine (suprapusă, 15 cadre decalaj între segmente de jos în sus): `hips` coboară (z −0.28 m) și se mută înapoi (+X, spre exterior, 0.12–0.18 m), `thigh.*` flexie ~55° (X), `shin.*` ~ −60° (genunchi 40–60°), `spine` +20°, `chest` +25° (înainte), `neck` +10°, `head` înclinare spre fetiță +8° (roll) și pitch compensat ca privirea să rămână pe fața fetiței.
- Echilibru: proiecția centrului de masă (hips+chest) rămâne în poligonul tălpilor: pe măsură ce chest merge înainte (−X, spre fetiță), hips merge înapoi. Verificare: x(CoM) în [min, max] al tălpilor ± 3 cm.
- `foot_ik` mamă: plantat, fix (fără alunecare), ușor pivot permis doar în afara contactului. Eventual un micro-pas la cad. ~130 pentru naturalețe (opțional).
- Anticipație: mică ridicare (2 cm, ~6 cadre) a umerilor/pieptului înainte de coborâre; settle la final cu overshoot 3° pe `chest`.

## 4. Privire și clipit
- `privire` e țintă în world-space, un obiect pentru fiecare personaj, cheie pe poziție.
- Fetița: 0–20 spre orizont (+X, nivel ochi); 20–125 spre fața mamei (urmărește fața în timp ce mama coboară); 125–285 pe ochii mamei (fixă, cu micro-saccade 1 cm la ~3 s); 285+ ușor pe lateral (cădere de privire, relaxare).
- Mama: 0–30 spre fetiță în depărtare (sau la jumătate); 40–165 pe ochii fetiței (țintă urmărește capul fetiței cu offset); 165–285 pe ochii fetiței; la îmbrățișare capul se apropie și privirea coboară ușor/se închide 230–245.
- Capul urmărește ochii cu întârziere: rotația `head` a rămas în urmă 4–6 cadre față de mișcarea `privire`, ochii 0–2 cadre (ochii pleacă primii). Implementare: cheie `head` shiftată cu +5 cadre față de cheile `privire`; ochii (Damped Track) urmează `privire` direct.
- Clipire: `clipire` 0→1→0 în 4 cadre (0→1 în 1.5, ținut 0.5, 1→0 în 2); intervale aleatoare (seed fix) 2–4 s (60–120 cadre), dar **nu** în intervalul 125–175 (contact vizual cheie) — se mută înainte/după. Cele două personaje au programări diferite (decalaj ≥ 15 cadre).

## 5. Zâmbet
- `zambet`: fetița 0 → 0.25 (cad. 30, curiozitate) → 1.0 (130–150, ease out) → 0.8 (200+, ușor relaxat, cu variație ±0.05 cu zgomot). Mama 0.15 → 0.5 (cad. 40–100) → 1.0 (130–150) → 0.9 hold. Zâmbetul mamei începe cu ~8 cadre înainte de al fetiței. Atenție: fără salt, curbe Bezier, nu liniar.

## 6. Îmbrățișarea
- Brațele mamei: `hand_ik.L/R` influență 0 → 1 (FK→IK) în ~12 cadre, între cad. 160–172, când brațele sunt deja deschise din FK (pregătit 150–160). Brațul unul (R) primul, L cu +4 cadre, ca să fie asimetric/natural.
- Țintele: dacă `B` = poziția world a spatelui fetiței (osul `chest`/`spine` fetiță + normală înapoi, adică spre −X relativ la fața ei), țintele sunt: mâna R la `B` + (0, −0.10, +0.03) (umărul stâng al fetiței), mâna L la `B` + (0, +0.10, −0.02), plus **offset de siguranță 1–2 cm** pe normala suprafeței (spate). Calcul: se alege un punct pe suprafață (raycast din sus/din spate pe mesh-ul fetiței) și se adaugă 0.015 m pe normală. Țintele sunt copii ale unui Empty urmărind `chest` fetiță cu mici balansuri (deci urmăresc respirația/leagănul).
- Traseu: mâna pleacă din lateral (deschis), trece prin exteriorul corpului fetiței (nu prin față), se închide spre spate; cot sus ~20°, `pole` plasat în exterior/jos ca să nu lovească cutia toracică.
- Fetița: brațele (FK) ridicate la 160–195: `upper_arm` abducție ~100°, `forearm` ~40°, mâinile ajung la umerii/gâtul mamei în world-space (mici IK cu aceeași tehnică, influență 0→1), cu offset 1.5 cm; apoi cap înclinat 8° spre mamă, ușor pe vârfuri (talpa ridică 1–2 cm, `foot_ik` z, fără alunecare).
- Menținere 205–285: balans comun foarte mic (translație ±1 cm a ambelor, rotație ±1.5°) cu zgomot; respirația separată.
- **Verificare intersecții** (offline, la fiecare cadru): `bmesh` → obiectele evaluate (`depsgraph`), transformate în world, `BVHTree.FromBMesh`; pentru fiecare pereche (obiect Mama, obiect Fetița) `tree_a.overlap(tree_b)` ≠ [] = eșec. **Perechi permise să se atingă: niciuna.** Toleranță: gap minim ≥ 5 mm; se măsoară cu `find_nearest` din centrul fiecărui vârf (sub-eșantionat) și se raportează dacă < 5 mm. Se rulează la fiecare cadru în intervalul 100–300, la fiecare 3 cadre în rest. Se exclud perechi din același personaj. Raport: cadru, pereche, adâncime.

## 7. Interpolare
- Bezier, handle-uri `AUTO_CLAMPED`; plantările tălpilor și pauzele = chei identice cu CONSTANT sau handle vectoriale; evităm LINEAR. Fără NLA; o singură action per rig.
- Idle: modifier F-curve `NOISE` pe `hips` z (amplitudine 2–3 mm, scale ~60 cadre) și pe `chest` X rot (0.6°, scale 90), `head` Z rot (0.8°, scale 70); faze diferite per personaj (`phase` ≠). Pe `privire` un noise de 5 mm (micro-saccade).
- Animația de respirație: `chest` scale nu se folosește (rigid); doar rotație X ±0.7° la 0.25 Hz.

## 8. Cameră (pentru decor/coordonator)
- Recomandat: cameră **statică la nivel mediu (z≈1.0, 3/4 din față)** care încadrează x ∈ [−2.8, 1.6] pe tot parcursul, apoi **push-in lent** (dolly 8–10%, 150–300, ease in/out) spre grupul de îmbrățișare. Fără tremur. Alternativ static complet pentru primul test (mai robust). Țintă `Track To` pe punctul (−0.15, 0, 0.9).
- La final (285–300) cadrul se stabilizează, fără zoom mai mult.

## 9. Riscuri și detecție automată
| Risc | Detecție |
|---|---|
| Picior alunecă pe podea | pentru fiecare plantare, Δ poziție world a `foot_ik`/călcâiului < **3 mm** între cadre consecutive de sprijin; și talpa z ∈ [0, 5 mm] |
| Piciorul pătrunde în podea | min z al mesh-ului tălpii ≥ −2 mm în toate cadrele |
| Intersecție mamă–fetiță | BVH overlap / distanță minimă (secțiunea 6); mai ales brațe-spate, cap-cap, fustă-genunchi |
| Păr lung mamă penetrează fetița/propriul corp la aplecare | pereche (păr_mamă, corp_fetiță/corp_mamă) în verificarea BVH; remediere: trimite părul înapoi (+X), roteste capul, sau păr rigid cu ușor offset |
| Fustă/rochie fetiță sau mamă în conflict cu brațele/picioarele | idem BVH; reducere unghi genunchi sau mutare mâini |
| Dezechilibru (mamă) | proiecția CoM în afara tălpilor ±3 cm → raport |
| Brațe IK flip / rotație bruscă | viteza unghiulară pe `forearm` și `upper_arm` > 25°/cadru → raport; pole bine plasat |
| Mers rigid/robotic | verificare vizuală pe 3 cadre per pas + grafic `hips` z (trebuie sinus ușor) |
| Privire nenaturală (ochi se întorc prea mult) | unghi `eye` vs `head` < 35° |
| Lipsă mișcare (static) | RMS mișcare oase > prag minim pe fiecare fereastră de 30 cadre |
| Clipire în moment cheie | listă cadre `clipire` > 0.5 nu include 125–175 |

Fluxul de lucru: `anim_*.py` setează chei → `verifica.py` calculează cele de mai sus pe toate cadrele → randare doar la cadrele cheie (0, 40, 80, 125, 165, 200, 250, 299) pentru aprobare, apoi randare completă.

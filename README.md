# 🌙 Baby Video Studio

Aplicație pentru Windows care transformă o melodie (de exemplu, de la Suno) și câteva imagini într-un videoclip animat MP4, gata de YouTube. Totul rulează pe calculatorul tău, gratuit și fără cont. Internetul e necesar doar o dată, ca să se descarce modelul de recunoaștere a vocii.

## Cum pornești aplicația

1. Fă dublu clic pe **`start.bat`**.
2. Așteaptă câteva secunde. Aplicația se deschide singură în browser, la adresa http://localhost:8501.
3. Lasă deschisă fereastra neagră cât timp lucrezi. Când o închizi, aplicația se oprește.

Ai nevoie de Python și FFmpeg. Pe acest calculator sunt deja instalate. Pe alt calculator, rulează o singură dată:

```
winget install Python.Python.3.12
winget install Gyan.FFmpeg.Essentials
```

## Cum faci un videoclip

1. În stânga, **creează un proiect nou** și dă-i un nume.
2. **Adaugă melodia și imaginile.** Le poți încărca sau poți apăsa „Preia fișierele din folderul input/”.
3. La fiecare imagine, scrie în **Ce se vede în imagine** câteva cuvinte, de exemplu `fetiță, ursuleț, lună`.
4. **Scrie povestea** și lipește **Versurile melodiei** exact cum se cântă, cu refrenele repetate, împărțite cu `[Strofa 1]`, `[Refren]`, `[Strofa 2]`, `[Strofa 3]`, `[Refren final]`, `[Outro]`.
5. La secțiunea 5 lasă alegerea **✨ Sincronizare automată cu vocea (AI local)** și apasă „Sincronizează automat”. Verifică doar rândurile marcate cu ⚠️. Modul manual, **Sincronizat cu versurile**, rămâne disponibil.
6. Apasă **Previzualizare rapidă** pentru 30 de secunde la rezoluție mică.
7. Apasă **Generează videoclipul complet**. Videoclipul folosește exact timpii și imaginile din cronologie, iar fișierul apare în folderul `output/`.

Un cântec de aproape 3 minute durează în jur de 2 minute. La a doua randare, scenele neschimbate se refolosesc și merge mai repede.

### Sincronizarea automată cu vocea (AI local)

1. Apasă **✨ Sincronizează automat**. Modelul de recunoaștere a vocii (faster-whisper, `large-v3-turbo`) rulează pe procesor, fără placă video dedicată. Pentru un cântec de 4 minute durează cam un minut și jumătate. Prima dată se descarcă modelul (~1,6 GB). Analiza se păstrează în `cache/voce/`, deci aceeași melodie se sincronizează a doua oară într-o secundă, chiar dacă ai schimbat versurile.
2. Aplicația aliniază **versurile tale exacte** cu cuvintele auzite, în ordine, cu toate refrenele repetate. Textul vine mereu din versurile tale; modelul arată doar *când* se cântă.
3. Pauzele instrumentale de cel puțin 4 secunde devin rânduri 🎵 separate, fără versuri. Un rând 🎤 înseamnă că s-a cântat ceva ce nu apare în versurile tale, de exemplu un refren repetat încă o dată.
4. Fiecare rând are o siguranță (coloana **Sigur**). Rândurile ⚠️ sunt nesigure: modelul nu le-a auzit clar și timpul lor a fost așezat între vecini. Apasă **⏭️ Următorul rând de verificat**: se aude bucata lui, de la o secundă înainte. Mută începutul sau sfârșitul cu −0,5 / −0,1 / +0,1 / +0,5 s, alege altă imagine sau apasă **✔️ E corect**.
5. Imaginile sunt alese imediat de **storyboard-ul automat** (mai jos).

**Nu e perfect.** La melodiile încercate, timpii au fost în medie la câteva zecimi de secundă de începutul real al versului, fără să fie decalați constant într-o direcție. Ascultă o dată rezultatul înainte de randare.

Dacă muzica acoperă mult vocea, poți instala din aplicație **separarea vocii (Demucs)**, opțional, aproximativ 1 GB. Adaugă 1–2 minute la analiză. Atenție: la melodia „Țup” rezultatul a fost **mai slab** cu separare (o strofă întreagă n-a fost auzită), așa că folosește-o doar când rezultatul fără separare are multe rânduri ⚠️.

Dacă memoria nu ajunge, aplicația trece singură la un model mai mic (`small`, mai puțin precis). Dacă nici acela nu încape, îți cere să închizi alte programe.

### Storyboard automat: imaginea fiecărei scene

După ce rândurile au timpi (automat sau marcați de tine), apasă **✨ Creează storyboard automat** la pasul 3.

1. Un model vizual mic (**SigLIP 2** de la Google, gratuit) rulează pe procesor și se uită la fiecare imagine: personaje, obiecte, acțiuni, decor, momentul zilei. Prima dată se descarcă (~370 MB); o imagine se analizează o singură dată (`cache/imagini/`), oricâte proiecte o folosesc. Sub fiecare imagine apare ce a văzut: „👁️ Se vede: iepuraș, morcov, gard…”.
2. Aplicația citește ce se cântă în fiecare vers și în toată strofa (iepuraș, morcov, buburuză, apus, doarme…) și caută imaginea care arată aceste lucruri. **Descrierile tale de la fiecare imagine și numele fișierelor contează și ele**: dacă descrierea conține cuvinte din vers („îl salută frumușel”) sau numele strofei („strofa 2”, „refren”), imaginea e preferată acolo.
3. Versurile la rând despre același lucru devin **o singură scenă**, de obicei de 5–12 secunde, schimbată de preferință la o strofă nouă. Pauzele instrumentale lungi pot rămâne pe aceeași imagine. **Timpii melodiei nu se schimbă.**
4. Refrenele repetate pot refolosi imaginile lor; celelalte imagini nu se repetă fără motiv. Mișcarea camerei e aleasă singură: zoom lent sau panoramare discretă, cu tranziții line.
5. Lista de scene arată timpul, versurile, imaginea, **potrivirea** (în procente) și o sugestie. Scenele ⚠️ au o imagine nepotrivită; sugestia spune ce lipsește („Adaugă o imagine cu: buburuză”). Bifa **Arată doar scenele care necesită verificare** le lasă doar pe acestea.
6. Schimbă imaginea unei scene direct în listă. **Imaginile alese de tine rămân** când apeși din nou butonul, cu excepția cazului în care bifezi „Înlocuiește și imaginile alese de mine”.

**Limite.** Modelul înțelege bine lucrurile clare (morcov, fluturi, miel, ursuleț, apus, cuib, mamă cu bebeluș), dar poate greși detaliile mici sau confunda animale pufoase. Cuvintele pe care le recunoaște sunt într-o listă fixă de ~50 de lucruri din cântecele pentru copii (`baby_video_studio/pictures.py`). Fără internet la prima pornire, sau dacă modelul nu pornește, imaginile se aleg doar după nume și descrieri, iar aplicația îți spune asta. Povestea scrisă la pasul 2 nu este folosită de storyboard-ul automat; folosește descrierile de la fiecare imagine.

### Cronologia sincronizată manual

1. **Creează rândurile din versuri.** Fiecare rând cântat devine un rând în cronologie, inclusiv refrenele repetate. Primul rând este introducerea instrumentală și începe la 0:00. Un `[Refren]` fără versuri sub el repetă primul refren. Imaginile sunt sugerate imediat.
2. **Marchează timpii ascultând.** Pornește melodia din player. Când începe rândul încadrat cu roșu, apasă tasta **M** sau butonul roșu. Același marcaj încheie rândul de dinainte. Bara de spațiu pornește și oprește melodia, iar „⏪ 3 s” dă înapoi. „Anulează ultimul marcaj” șterge ultimul timp. Un clic pe un rând îl alege pentru un marcaj nou și redă bucata lui, de la o secundă înainte. Viteza 0,75× sau 0,5× ajută doar la ascultare; videoclipul păstrează melodia neschimbată. În timp ce asculți, imaginea de sus arată ce va fi pe ecran în acel moment, deci poți verifica sincronizarea înainte de randare.
3. **Creează storyboard-ul** (secțiunea de mai sus), apoi, dacă vrei, deschide **Toate rândurile** ca să modifici rând cu rând. Poți schimba imaginea, scrie un timp (de exemplu `1:15.5`), adăuga un rând (de exemplu o pauză instrumentală) sau șterge unul. Rândurile consecutive cu aceeași imagine formează o singură scenă, fără tranziție.

Aplicația randează doar când cronologia este completă: fiecare rând are timp, rândurile sunt în ordinea din melodie, fără suprapuneri, și fiecare imagine stă pe ecran destul cât să se termine tranziția. Fiecare tranziție **începe exact la timpul marcat**, deci imaginea nouă nu apare înaintea versului ei; ea devine complet vizibilă după durata tranziției.

**În modul manual, timpii sunt cei marcați de tine.** Precizia depinde de cât de repede apeși tasta, așa că ajută să corectezi cu butoanele −/+ din player sau cu zecimi de secundă în tabel.

Planul vechi rămâne disponibil la alegerea **Estimat automat**. Acolo timpii sunt doar aproximați din text și din muzică.

### 🌟 Personaj vorbitor – Lip Sync

Un videoclip vertical (1080×1920, 30 FPS, pentru Reels și Shorts) în care personajul vorbește cu vocea ta. Alege sus, sub numele proiectului, **„🌟 Personaj vorbitor – Lip Sync”**.

1. **Personajul** (o singură dată): „Creează un personaj nou”, cu un nume și o imagine PNG cu **fundal transparent** și gura ușor deschisă. Aplicația găsește singură gura și ochii și îți arată toate expresiile: gura închisă, puțin deschisă, deschisă, larg deschisă, rotunjită și clipitul. Dacă nu le-a găsit bine, le muți din „Corectează pozițiile”. Profilul se păstrează în `personaje/` și îl alegi în orice proiect nou.
2. **Variante (opțional, cel mai bun rezultat):** încarcă imagini cu același personaj, în aceeași poziție, doar cu gura sau ochii altfel (închisă, puțin deschisă, deschisă, larg deschisă, rotunjită, ochi închiși). Aplicația ia din ele doar zona gurii sau a ochilor, o aliniază și o îmbină peste imaginea principală. Pentru formele fără variantă, gura se face din imaginea principală.
3. **Vocea:** MP3 sau WAV. Cuvintele sunt recunoscute local (faster-whisper, același model ca la sincronizarea versurilor), iar gura se mișcă pe silabele lor: deschisă la „a”, lățită la „e/i”, rotunjită la „o/u”, închisă la „m/b/p”. Volumul vocii spune cât de mult se deschide. Muzica de fundal nu mișcă gura; în pauze gura rămâne închisă.
4. **Decorurile:** imagini fără personaj, în ordinea în care le alegi. Decorul se schimbă într-o pauză a vorbirii, cu o trecere lină. Decorul poate fi tăiat pe margini ca să umple ecranul vertical; personajul niciodată. Fără decor, personajul apare pe un cer de seară.
5. **Mișcarea:** cât se deschide gura, legănarea (0 = nemișcat), clipitul (pornit sau oprit, cât de des, cât de repede) și cel mai scurt timp pe un decor.
6. **👀 Previzualizare 5 secunde** (alegi de unde începe), apoi **✨ Generează animația** și **⬇️ Descarcă MP4**. Un minut de voce se randează în aproximativ 2–3 minute.

**Limite.** Nu e un model AI: imaginea nu se redesenează, doar gura și ochii se schimbă, iar personajul se leagănă ușor. Sincronizarea urmează silabele și vocalele, nu fiecare sunet. Detectarea automată a gurii și ochilor e făcută pentru personaje cu pielea galbenă sau portocalie și ochi albaștri (ca Steluța); la alte personaje folosește corectarea manuală sau variantele.

### 🎬 Animație automată – Personaje multiple

Un videoclip animat cu mai multe personaje care se mișcă în același timp, construit aproape singur din melodie și versuri. Alege sus **„🎬 Animație automată – Personaje multiple”**.

1. **Melodia și versurile**, cu titluri ca `[Strofa 1]` și `[Refren]`.
2. **Sincronizarea cu vocea**: aceeași ca la videoclipul muzical. Timpii se pot corecta, opțional.
3. **Personajele și decorurile** din bibliotecă. Primul personaj ales e personajul principal; alegi și cine cântă (gura i se mișcă după voce). Fluturii și Norișorul (🦋) sunt desenați de program; decorurile 🎨 la fel. Personajele tale vin din `personaje/` (le poți adăuga și de aici: PNG cu fundal transparent). O singură dată pe personaj, în „Pregătește personajele pentru animație”: ce fel de personaj este, dacă zboară, cum îl numesc versurile și, opțional, o imagine cu mâna ridicată pentru salut. Decorurile se adaugă în `decoruri/` (fără personaje în ele); aplicația vede singură dacă sunt de zi sau de noapte și ce conțin.
4. **Logo-ul**, ca la celelalte videoclipuri.
5. **✨ Generează animația automat**: aplicația împarte cântecul în scene de 7–15 secunde, dă fiecărei strofe decorul potrivit (refrenele îl păstrează pe al lor, „noapte”, „somn”, „lună” aleg un decor de noapte), pune în fiecare scenă personajele despre care se cântă, pe cel care cântă și un prieten, și alege ce face fiecare pe fiecare vers. Apoi face o previzualizare la rezoluție mică (un cântec de 3 minute: cam 2 minute).

**Ce înțelege din versuri** (catalogul `defaults/actiuni.json`, pe care îl poți completa cu cuvinte noi):

- acțiuni: „sare”, „țup”, „hop” → sare; „dansează”, „se joacă” → dansează; „pas”, „merge” → merge; „zboară” → zboară; „nani”, „somn” → se leagănă; „salută” → salută;
- interacțiuni: „lângă”, „aproape” → unul vine lângă altul (un fluture îl urmărește); „toți”, „la fel ca el” → ceilalți fac la fel, puțin mai târziu; „dansăm”, „de mână” → dansează împreună;
- intrări: „apar”, „vine”, „sosesc” → personajul intră în cadru;
- efecte: „stele”, „strălucesc” → stele care sclipesc; „balon” → baloane; „flori” → flori care se leagănă; „nor” → nori; „lumină”, „vis” → luminițe.

Unde versurile nu cer nimic, fiecare personaj primește o mișcare blândă potrivită lui, fără să o repete de două ori la rând.

**Schimbi doar ce nu-ți place.** Alegi scena și: **🔄 Regenerează scena** (alte alegeri pentru aceleași versuri), **🎲 Surprinde-mă** (aceleași personaje și acțiuni, alt aranjament), **🎭 Schimbă personajul**, **🎬 Schimbă animația**, **🏞️ Schimbă decorul**. Scena se previzualizează singură. Restul videoclipului și timpii nu se schimbă, iar la o nouă generare automată scenele schimbate de tine se păstrează. În „Mod avansat”: camera, efectele, interacțiunile, cât de ample sunt mișcările și **șabloanele de scene** (salvezi o scenă reușită și o aplici în alt cântec).

**Export:** **⬇️ Exportă MP4 la 1080p**, în 16:9 (YouTube) sau 9:16 (Shorts, Instagram, TikTok). Fiecare scenă desenată se păstrează în `cache/animatie/`: după o schimbare se redesenează doar scena schimbată și cele două vecine (pentru tranziții). Un cântec de 3 minute la 1080p: cam 8 minute prima dată.

**Unde stau personajele în decor.** La pasul 3, în „📐 Unde stau personajele în decor”, alegi o dată pentru fiecare decor: zona în care pot sta picioarele (albastru), cât de mici sunt personajele în spatele zonei (perspectiva) și obiectele pe care nu au voie să calce sau în spatele cărora nu au voie să stea (roșu: mingea, tufele, florile din față). În fața lor pot sta. Previzualizarea arată personajele unde le-ar pune o scenă, în 16:9 și 9:16. Zona se păstrează în `decoruri/decoruri.json` și se folosește în toate proiectele. Un decor fără zonă (⚠️ fără zonă) păstrează linia fixă de până acum. Decorurile pictate nu mai primesc nori și flori desenate de program, decât dacă le cer versurile.

**Decorul înțeles automat.** „🔍 Analizează decorul automat” (sau toate deodată) folosește un model local de adâncime (Depth Anything V2 Small, gratuit și pentru uz comercial, ~95 MB, descărcat o dată; cam o secundă pe decor). El găsește singur solul, perspectiva și obiectele și propune zona, pe care o poți corecta. Harta de adâncime se păstrează lângă decor (`<nume>.adancime.png`): ce e în fața unui personaj (florile, pietrele din față) se desenează peste el, așa că poate sta sau trece prin spatele lor, cât timp i se ascund doar picioarele. Cine intră în cadru și are florile în cale vine din spate, pe diagonală, crescând cu perspectiva. Un decor fără sol (un prim-plan cu o floare mare) e marcat așa și nu e ales pentru scene cu personaje, dacă ai altele. Decorurile noi se analizează singure când le adaugi.

**Stilul „Fără deformare”.** La pasul 5, „Mișcarea personajelor”: fiecare personaj rămâne exact ca în imaginea lui. Nu se turtește, nu sare mutând imaginea, nu merge alunecând; se leagănă ușor (cel mult 3°) cu picioarele pe podea, face un pas mic într-o parte la dans și apare lin când intră în scenă. Gesturile vin din **cadre**, încărcate la pasul 3 în „⚙️ Pregătește personajele”: același personaj în aceeași imagine, doar în altă poză (bate din palme, sare, salută, cu ochii închiși). Pe ritm, aplicația trece lin la cadru și înapoi, într-o zecime de secundă; un cadru puțin mutat se aliniază singur după cap și umeri. Fără cadru, palmele și săritura devin o legănare veselă, iar personajul nu clipește. În versuri, „clap” înseamnă și el bătut din palme.

**Palme din două cadre.** Cu cadrele „✋ Mâini depărtate” și „👏 Palmele lipite”, personajul trece pe ritm de la unul la altul (lipite pe bătaie). **Inimioare**: efect nou, câteva inimioare mici care apar, urcă puțin și dispar. **Prim-plan lent**: camera se apropie de un personaj ales (de primul, dacă nu alegi). Baloanele apar acum în orice scenă a melodiei, nu doar în primele 30 de secunde.

**Ajustări pe scenă** („⚙️ Mod avansat” din editorul de scene): **text pe ecran** (apare lin, sus la mijloc, după prima secundă, cu un font rotunjit care are ă, â, î, ș, ț), iar pentru fiecare personaj **„Loc ales de mine”** (stânga–dreapta și față–spate în zona sigură a decorului) și **mărimea**. „Adaugă în scenă” oferă orice personaj din bibliotecă, nu doar pe cele din proiect. Efect nou, **Confetti**: puține bucățele care cad încet, în spatele personajelor. Mișcare nouă, **„Leagănă lin (de culcare, max. 2°)”**: foarte lentă, în jurul tălpilor, pentru un personaj compus ca „Mama cu fetița în brațe”. „Post-refren” și „Pre-refren” nu mai sunt luate drept refren. Storyboard-ul pentru „Are mama o fetiță” se aplică cu `tools\storyboard_are_mama.py`.

**Brațe și picioare care se mișcă (scheletul).** La pasul 3, în „🦴 Scheletul personajelor”, alegi personajul și apeși „✨ Propune scheletul automat”: aplicația pune singură 15 puncte (creștet, gât, umeri, coate, încheieturi, șolduri, genunchi, glezne) după forma personajului. Le muți cu mouse-ul dacă nu sunt la locul lor și vezi pe loc personajul în repaus, la pas, bătând din palme, în aer, dansând și salutând. Cu schelet, personajul pășește cu adevărat (un genunchi sus, apoi celălalt), bate din palme pe ritm („bat din palme”, „bravo” în versuri), dansează cu brațele, salută cu mâna și se lasă pe genunchi la aterizare. Merge pentru personaje desenate din față, în picioare, cu brațele puțin depărtate de corp și picioarele vizibile. Desenarea folosește placa video (OpenGL, prin moderngl); fără ea, personajele se mișcă întregi, ca înainte.

**Animalele.** Un personaj de tipul „Animal” primește alt schelet: capul (se înclină ușor pe corp), urechile (se leagănă la dans, stau sus în aer și cad moale la aterizare), coada (dă din ea la mers și la dans), aripioarele (bat la dans, se strâng la palme) și tălpile (pași mici, una câte una). „✨ Propune scheletul automat” le găsește singur din formă: două forme sus sunt urechi, ce iese doar într-o parte e coadă, ce iese în ambele părți la mijloc sunt aripioare, două forme jos sunt tălpi; corectezi punctele cu mouse-ul. Lăbuțele pictate pe burtică rămân pe loc (mișcate, ar rupe burtica): la palme și la salut animalul răspunde din cap și din urechi. Animalele sunt mai mici decât un copil („Mărimea”, de pornire 0,6–0,8).

**Mersul.** Cine merge pășește cu pas egal, fără să sară, și se oprește lin. Cât timp merge nu sare și nu dansează: săritura sau dansul vin după ce se oprește.

**Siguranță pentru 0–2 ani**, în cod: mișcări care pornesc și se opresc lin, amplitudini mici, sclipiri lente (fără flash-uri), cel mult 5 personaje și 3 efecte pe scenă. Personajele de pe sol se micșorează singure ca să nu se atingă și să nu iasă din cadru; zburătorii se feresc unii de alții și de cei de pe sol.

**Limite.** Dintr-un PNG static se mișcă tot personajul (sare, se leagănă, se înclină, merge alunecând), nu brațele sau picioarele. Salutul cu mâna cere o imagine cu mâna ridicată; fără ea, personajul se leagănă prietenos. Arhitectura acceptă și părți separate (cum sunt aripile fluturilor) și alte poziții ale aceluiași personaj. Imaginile cu fundal trebuie decupate înainte (decuparea automată ar cere un model local de ~170 MB, neinstalat). Versurile sunt înțelese prin reguli, nu prin AI.

### Subtitrări YouTube (.srt)

După sincronizarea versurilor, secțiunea **📝 Subtitrări YouTube** (la finalul paginii) face fișierul de subtitrare din cronologie, fără o nouă analiză a melodiei.

1. Apasă **📝 Generează subtitrarea**. Fiecare vers devine o subtitrare, cu textul tău exact (cu diacritice) și cu timpii lui, inclusiv refrenele repetate. Pauzele instrumentale și rândurile 🎤 nu primesc subtitrare; un vers se termină acolo unde începe pauza.
2. Ascultă melodia în playerul secțiunii: sub el apare subtitrarea momentului, ca pe YouTube. Rândurile ⚠️ au sincronizare nesigură.
3. Corectează textul sau timpii direct în tabel (de exemplu `1:15.50`).
4. Apasă **⬇️ Descarcă subtitrarea .srt**. Butonul funcționează doar când toate subtitrările au timpi, nu se suprapun și nu trec de finalul melodiei; altfel aplicația spune ce trebuie corectat. Fișierul e UTF-8 și se numește după proiect, de exemplu `Tup_Tup_Iepuras_RO.srt`.
5. În YouTube Studio: videoclipul → **Subtitrări** → limba română → **Adaugă** → **Încarcă fișierul** → **Cu sincronizare**.

### Logo-ul canalului

În secțiunea **Logo canal** încarci logo-ul (PNG sau JPG), bifezi „Afișează logo-ul” și alegi când apare:

- **Pe toată durata videoclipului** (implicit): watermark în colț, în toate scenele, de la intro la outro, inclusiv în tranziții și în estomparea de la final. Pornește mic (8% din lățimea videoclipului), puțin transparent (65%), sus în dreapta, la 3% de margini, ca să nu acopere personajele. Mărimea, opacitatea și poziția se pot schimba.
- **Doar la început**: logo-ul apare peste primele secunde și dispare lin.

Logo-ul se pune peste videoclip după ce scenele și tranzițiile sunt gata, deci nu se mișcă odată cu camera și nu clipește la schimbarea imaginilor. Apare la fel în previzualizare și în MP4. Mărimea și marginea se calculează după lățimea videoclipului, așa că se potrivesc și pe un videoclip vertical (9:16). Butonul de salvare păstrează logo-ul și setările pentru proiectele viitoare. Logo-urile salvate înainte de această opțiune, cu mărimea și opacitatea neschimbate (15%, 85%), trec singure la valorile watermark-ului. Poți adăuga logo-ul și pe un videoclip deja generat, din aceeași secțiune; se creează un fișier nou, cu sunetul copiat identic.

Ca logo-ul să nu aibă un fundal vizibil, folosește un PNG cu fundal transparent. La un JPG sau la un PNG fără transparență, fundalul imaginii rămâne vizibil.

### Cum scrii povestea

```
La început, o fetiță doarme liniștită îmbrățișându-și ursulețul.
Apoi apare un băiețel blond care doarme pe un nor pufos.
Mai târziu, o oiță doarme printre stele.
Luna strălucește blând.
Repetă scenele natural până la final.
```

Pentru un moment exact, pune timpul la începutul rândului: `1:15 oița doarme printre stele`. Asta funcționează când versurile nu au secțiuni.

Când versurile au secțiuni, propozițiile se distribuie în ordine peste strofe și primul refren, iar refrenele următoare le refolosesc. Poți lega o propoziție de o secțiune anume, iar propozițiile următoare rămân la aceeași secțiune până la alt titlu:

```
Strofa 1: Fetița doarme cu ursulețul.
Refren: Mama îi dă un sărut de noapte bună.
Strofa 2: Un iepuraș doarme în grădină.
```

### Timpii din planul estimat automat

Coloana **Timp** arată de unde vine fiecare început de scenă:

| Semn | Înseamnă |
|---|---|
| ≈ | Estimat din cantitatea de text și din schimbările muzicii |
| 📌 | Scris de tine în versuri, de exemplu `[1:15.5] Nani, nani` |
| ✍️ | Corectat de tine în tabel |

Acest mod nu ascultă vocea, deci timpii ≈ sunt aproximativi. Ascultă melodia și scrie timpul corect în tabel, de exemplu `1:15.5`. Sfârșitul unei scene și începutul următoarei sunt același moment, așa că e suficient să-l schimbi pe unul. După ce ai corectat timpi, aplicația îți cere o bifă înainte să refacă planul, ca să nu-i pierzi din greșeală.

### Ce știe și ce nu știe să facă

- **Cu versuri sincronizate, storyboard-ul automat „vede” imaginile** cu un model local și le potrivește cu ce se cântă. În modul **Estimat automat**, imaginile se aleg doar după numele fișierelor și descrierile tale: un fișier numit `Teddy Bear.png` sau descris `ursuleț` se potrivește cu „ursulețul”; dacă nu găsește o potrivire, alege singură și marchează scena cu ⚠️.
- **Toate imaginile apar cel puțin o dată**, dacă melodia e destul de lungă. Dacă nu, aplicația îți spune care nu au încăput. Refrenele repetate refolosesc imaginile primului refren.
- **Modul Cinematic mișcă doar camera** și adaugă stele, particule, nori și lumină. Personajele nu se mișcă.
- **Melodia rămâne neschimbată**: nu este accelerată, încetinită sau estompată. Este doar convertită în AAC, formatul cerut pentru MP4.
- **Scenele se schimbă la schimbările din melodie**, detectate aproximativ. Timpii scriși de tine în poveste au prioritate. Bifa „Sincronizează scenele cu muzica” poate fi oprită, iar scenele devin egale ca durată.
- **Versurile nu apar în videoclip.** Ele ajută la alegerea imaginilor și la cronologie.

## Unde se află fișierele

| Folder | Conținut |
|---|---|
| `input/` | Fișierele tale originale. Aplicația doar le copiază. |
| `projects/` | Proiectele salvate, cu copii ale melodiei și imaginilor. |
| `output/` | Videoclipurile finale. Niciun videoclip existent nu este suprascris. |
| `cache/` | Scene refolosibile (se pot goli oricând din aplicație) și analizele vocii (`cache/voce/`) și ale imaginilor (`cache/imagini/`), păstrate la golire. |
| `defaults/` | Logo-ul și setările salvate pentru proiectele viitoare. |
| `personaje/` | Personajele vorbitoare salvate: imaginea, pozițiile gurii și ochilor, variantele. |
| `decoruri/` | Decorurile bibliotecii de animație, cu ce s-a văzut în ele. |
| `sabloane/` | Scenele salvate ca șablon, refolosibile în orice proiect. |

## Probleme frecvente

- **„Nu găsesc programul ffmpeg”**: rulează comanda de instalare de mai sus și pornește din nou `start.bat`.
- **Browserul nu s-a deschis**: intră manual la http://localhost:8501.
- **Portul este ocupat**: aplicația rulează deja. Închide cealaltă fereastră neagră.

## Pentru dezvoltatori

```
.venv\Scripts\python.exe -m pytest
```

Stadiu: modul Cinematic, sincronizarea manuală și sincronizarea automată cu vocea (faster-whisper pe CPU, int8) și storyboard-ul automat (SigLIP 2 prin onnxruntime pe CPU) sunt funcționale. Urmează modul Hibrid.

Animația automată: `motions.py` (catalogul de mișcări, tempoul), `stage.py` (scena pe straturi, potrivirea în cadru, randarea pe scene păstrate), `effects.py` (decoruri și efecte desenate, personaje desenate), `actions.py` (regulile pentru versuri), `library.py` (personaje, decoruri, șabloane), `director.py` (planul automat și schimbările pe scene), `ground.py` (zona sigură din decor, perspectiva, obstacolele, ce se desenează peste personaje), `depth.py` (modelul de adâncime și analiza decorului), `rig.py` (scheletul: plasa de triunghiuri, ponderile, pozele văzute din față, desenarea pe placa video) și `rig_editor.js` (editorul punctelor). Mișcările descriu deja și unghiurile brațelor și picioarelor (`Pose.joints`, `motions.JOINTS`), pentru scheletul 2D din etapa următoare; o imagine simplă le ignoră. Testele de 10 secunde cu Fetița: `tools\test_p0.py` (zona pusă de mână) `tools\test_p1.py` (decorul analizat automat) `tools\test_p2.py` (Fetița cu schelet) `tools\test_p3.py` (Fetița cu iepurașul, vulpița și puișorul) `tools\test_fara_deformare.py` (aceeași scenă, fără deformare) și `tools\test_are_mama.py` (testul de 20 s pentru „Are mama o fetiță”). Prototipul cu scena scrisă de mână: `tools\prototip_animatie.py`. După o schimbare în felul în care se desenează, mărește `CLIP_VERSION` din `stage.py`, ca scenele păstrate să fie desenate din nou.

După ce schimbi lista `CONCEPTS` din `baby_video_studio/pictures.py`, refă `concepts.npz` (descarcă o dată modelul de text, 1,1 GB):

```
.venv\Scripts\python.exe tools\make_concepts.py input\images
```

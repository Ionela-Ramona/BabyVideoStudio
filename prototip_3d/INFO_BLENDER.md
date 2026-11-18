# Blender – info

- Cale: `D:\Tools\Blender\blender-4.5.16-windows-x64\blender.exe` (portabil, SHA256 verificat)
- Versiune: 4.5.16 LTS, Python 3.11.15
- Cycles (doar pentru evidenta): `AMD Radeon 780M Graphics` (HIP) + CPU Ryzen 7 8845HS. CUDA/OptiX/oneAPI: nimic.
- EEVEE (`BLENDER_EEVEE_NEXT`) ruleaza OK headless (`-b`); EEVEE Next nu are fallback CPU, deci randeaza pe GPU (Radeon 780M, iGPU cu RAM partajat). `gpu.platform` nu e interogabil in `-b`.
- Masurare: `.\masoara.ps1 -b --factory-startup --python x.py '--' args` (ghilimele in jurul `--`, altfel PowerShell il inghite). Log: `masoara.log` langa script.

## Masuratori (scena: plan + 5 sfere Principled + sun + area, `masoara.ps1`)
| Test | Wall | Blender Time | Peak RAM (WS / private) |
|---|---|---|---|
| Still 960x540, 16 spl (rulare la rece) | 12.6 s | 10.0 s | 1.9 / 2.4 GB |
| Still 1920x1080, 64 spl (cache shadere cald) | 4.5 s | 3.7 s | 1.7 / 2.2 GB |
| Animatie 30 cadre 960x540, 16 spl | 8.8 s total | ~0.2 s/cadru (primul 1.7 s) | 2.4 / 2.7 GB |

Prima rulare include compilarea shaderelor (~9 s); ulterioarele sunt rapide. Blender "Mem" raportat doar ~50-75 MB (VRAM nu e numarat); RAM-ul de proces e dominat de driver/GPU.
Avertismente: niciunul (stderr gol, exit 0). Scena reala (personaje+decor, ombre, AO) va fi mai lenta decat 0.2 s/cadru.

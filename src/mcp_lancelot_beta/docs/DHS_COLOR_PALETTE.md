# DHS Color Palette (reference)

Source: "MDG PROMPT 3 DHS COLOR PALETTE.txt", supplied by the user on 2026-11-12. The same text, as an LLM prompt, is
`lib/tools/mermaid/PROMPTS/MDG PROMPT 3 DHS COLOR PALETTE.txt` (used by `lib/tools/mermaid/lib/prompts.mjs`; that file
is a verbatim prompt and is not edited). This page is the same data reformatted for people and code. Values are copied
as published; see "Checks on the source" for the three entries whose HTML and RGB values disagree.

## Rules (from the source)

* The DHS Color Palette is the only approved color system for DHS and its components; variation from these colors
  is prohibited. It aligns with the US Web Design System (USWDS).
* **Primary** colors are required for key design elements (headings, features, etc.). **Secondary** colors are used
  sparingly, to supplement the primary colors or draw attention to specific content.
* **Gradient** colors (the color wheel below) may be used as backgrounds and for graphic elements and illustrations.
  The primary and secondary colors are the "50" step of each gradient (marked ★).
* HTML/RGB values are for web, video, mobile and desktop printing; CMYK values are for offset printing.
* **Section 508:** color must not be the only way information, an action, a prompt or a status is conveyed (the same
  information must also be in on-screen text or another visual difference); foreground and background must contrast
  at least **4.5:1**. Recommended checker: the Color Contrast Analyzer (CCA),
  https://www.dhs.gov/publication/web-accessibility-toolbar. The DHS seal is exempt from the contrast rule.
* **Restricted colors** (campaign and component colors, below) may be used only for those specific missions, or with
  explicit approval from HQ OPA.

## Primary and secondary colors

| Name | Role | HTML | RGB | CMYK |
| --- | --- | --- | --- | --- |
| dhs-blue | Primary | `#005288` | 0, 82, 136 | 100, 45, 0, 37 |
| dhs-gray | Primary | `#c0c2c4` | 192, 194, 196 | 0, 0, 0, 28 |
| dhs-dark-gray | Primary | `#5a5b5d` | 90, 91, 93 | 0, 0, 0, 79 |
| dhs-red | Secondary | `#c41230` | 196, 18, 48 | 0, 100, 79, 20 |
| dhs-light-blue | Secondary | `#0078ae` | 0, 120, 174 | 100, 16, 0, 27 |
| dhs-green | Secondary | `#5e9732` | 94, 151, 50 | 56, 0, 100, 27 |

Plus `black` `#000000` (RGB 0, 0, 0; CMYK 0, 0, 0, 100) and `white` `#ffffff` (RGB 255, 255, 255; CMYK 0, 0, 0, 0).

## Gradient colors (color wheel): HTML values

Name pattern: `<family>-<step>`, e.g. `dhs-blue-20`; step 50 is the plain name (`dhs-blue`).

| Step | dhs-blue | dhs-gray | dhs-dark-gray | dhs-red | dhs-light-blue | dhs-green |
| --- | --- | --- | --- | --- | --- | --- |
| 90 | `#000305` | `#080808` | `#040404` | `#080102` | `#000507` | `#040602` |
| 80 | `#001726` | `#363637` | `#19191a` | `#37050d` | `#002231` | `#1a2a0e` |
| 70 | `#002b47` | `#646566` | `#2f2f30` | `#660919` | `#003e5a` | `#314f1a` |
| 60 | `#003e67` | `#929395` | `#444547` | `#950e24` | `#005b84` | `#477326` |
| 50 ★ | `#005288` | `#c0c2c4` | `#5a5b5d` | `#c41230` | `#0078ae` | `#5e9732` |
| 40 | `#3d7ca5` | `#cfd1d2` | `#828284` | `#d24b62` | `#3d98c1` | `#85b063` |
| 30 | `#7aa5c1` | `#dedfe0` | `#a9aaab` | `#e08493` | `#7ab9d5` | `#abc994` |
| 20 | `#b8cfde` | `#edeeee` | `#d1d1d2` | `#eebdc5` | `#b8d9e8` | `#d2e2c6` |
| 15 | `#d6e3ec` | `#f5f5f6` | `#e5e5e5` | `#f6d9de` | `#d6e9f2` | `#e5eede` |
| 10 | `#f5f8fa` | `#fcfdfd` | `#f8f8f9` | `#fdf6f7` | `#f5fafc` | `#f9fbf7` |

## Gradient colors: RGB and CMYK

| Name | RGB | CMYK |
| --- | --- | --- |
| dhs-blue-90 | 0, 3, 5 | 100, 40, 0, 98 |
| dhs-blue-80 | 0, 23, 38 | 100, 39, 0, 85 |
| dhs-blue-70 | 0, 43, 71 | 100, 39, 0, 72 |
| dhs-blue-60 | 0, 62, 103 | 100, 40, 0, 60 |
| dhs-blue ★ | 0, 82, 136 | 100, 45, 0, 37 |
| dhs-blue-40 | 61, 124, 165 | 79, 44, 19, 1 |
| dhs-blue-30 | 122, 165, 193 | 54, 25, 15, 0 |
| dhs-blue-20 | 184, 207, 222 | 27, 10, 7, 0 |
| dhs-blue-15 | 214, 227, 236 | 15, 5, 4, 0 |
| dhs-blue-10 | 245, 248, 250 | 3, 1, 1, 0 |
| dhs-gray-90 | 8, 8, 8 | 0, 0, 0, 97 |
| dhs-gray-80 | 54, 54, 55 | 2, 2, 0, 78 |
| dhs-gray-70 | 100, 101, 102 | 2, 1, 0, 60 |
| dhs-gray-60 | 146, 147, 149 | 2, 1, 0, 42 |
| dhs-gray ★ | 192, 194, 196 | 0, 0, 0, 28 |
| dhs-gray-40 | 207, 209, 210 | 18, 13, 13, 0 |
| dhs-gray-30 | 222, 223, 224 | 12, 8, 8, 0 |
| dhs-gray-20 | 237, 238, 238 | 0, 0, 0, 7 |
| dhs-gray-15 | 245, 245, 246 | 0, 0, 0, 4 |
| dhs-gray-10 | 252, 253, 253 | 0, 0, 0, 1 |
| dhs-dark-gray-90 | 4, 4, 4 | 0, 0, 0, 98 |
| dhs-dark-gray-80 | 25, 25, 26 | 73, 67, 64, 78 |
| dhs-dark-gray-70 | 47, 47, 48 | 70, 64, 62, 61 |
| dhs-dark-gray-60 | 68, 69, 71 | 68, 60, 57, 42 |
| dhs-dark-gray ★ | 90, 91, 93 | 0, 0, 0, 79 |
| dhs-dark-gray-40 | 130, 130, 132 | 51, 43, 41, 6 |
| dhs-dark-gray-30 | 169, 170, 171 | 35, 28, 28, 0 |
| dhs-dark-gray-20 | 209, 209, 210 | 0, 0, 0, 18 |
| dhs-dark-gray-15 | 229, 229, 229 | 0, 0, 0, 10 |
| dhs-dark-gray-10 | 248, 248, 249 | 0, 0, 0, 2 |
| dhs-red-90 | 8, 1, 2 | 0, 88, 75, 97 |
| dhs-red-80 | 55, 5, 13 | 0, 91, 76, 78 |
| dhs-red-70 | 102, 9, 25 | 34, 99, 82, 51 |
| dhs-red-60 | 149, 14, 36 | 26, 100, 91, 26 |
| dhs-red ★ | 196, 18, 48 | 0, 100, 79, 20 |
| dhs-red-40 | 210, 75, 98 | 14, 85, 51, 1 |
| dhs-red-30 | 224, 132, 147 | 9, 59, 27, 0 |
| dhs-red-20 | 238, 189, 197 | 4, 30, 11, 0 |
| dhs-red-15 | 246, 217, 222 | 2, 16, 5, 0 |
| dhs-red-10 | 253, 246, 247 | 0, 3, 1, 0 |
| dhs-light-blue-90 | 0, 5, 7 | 100, 29, 0, 97 |
| dhs-light-blue-80 | 0, 34, 49 | 100, 31, 0, 81 |
| dhs-light-blue-70 | 0, 62, 90 | 100, 31, 0, 65 |
| dhs-light-blue-60 | 0, 91, 132 | 100, 31, 0, 48 |
| dhs-light-blue ★ | 0, 120, 174 | 100, 16, 0, 27 |
| dhs-light-blue-40 | 61, 152, 193 | 73, 27, 12, 0 |
| dhs-light-blue-30 | 122, 185, 213 | 50, 13, 9, 0 |
| dhs-light-blue-20 | 184, 217, 232 | 26, 5, 5, 0 |
| dhs-light-blue-15 | 214, 233, 242 | 15, 2, 2, 0 |
| dhs-light-blue-10 | 245, 250, 252 | 3, 0, 0, 0 |
| dhs-green-90 | 4, 6, 2 | 33, 0, 67, 98 |
| dhs-green-80 | 26, 42, 14 | 38, 0, 67, 84 |
| dhs-green-70 | 49, 79, 26 | 76, 44, 100, 44 |
| dhs-green-60 | 71, 115, 38 | 74, 33, 100, 21 |
| dhs-green ★ | 94, 151, 50 | 56, 0, 100, 27 |
| dhs-green-40 | 133, 176, 99 | 53, 13, 79, 1 |
| dhs-green-30 | 171, 201, 148 | 36, 7, 52, 0 |
| dhs-green-20 | 210, 226, 198 | 18, 3, 25, 0 |
| dhs-green-15 | 229, 238, 222 | 10, 1, 14, 0 |
| dhs-green-10 | 249, 251, 247 | 2, 0, 2, 0 |

## Example of correct use (from the source)

The source illustrates the color wheel with a figure (not included). Key elements use the 50 step; their accents use
the 30 step of the same family; the ring background uses a 15 step.

| # | Design element | Type | Primary color required | Color used |
| --- | --- | --- | --- | --- |
| 1 | Outer ring, text, inner feature | Key | Yes | dhs-blue |
| 2 | Ring background | Secondary | No | dhs-blue-15 |
| 3 | Green figure | Key | Yes | dhs-green |
| 4 | Green figure accent | Secondary | No | dhs-green-30 |
| 5 | Red figure | Key | Yes | dhs-red |
| 6 | Red figure accent | Secondary | No | dhs-red-30 |
| 7 | Blue figure | Key | Yes | dhs-light-blue |
| 8 | Blue figure accent | Secondary | No | dhs-light-blue-30 |

## Restricted colors

Only for the mission named, or with explicit approval from HQ OPA. The Old Glory colors are the official colors of
the U.S. government (no restriction is stated for them).

| Owner | Use | Name | HTML | RGB | CMYK | PANTONE |
| --- | --- | --- | --- | --- | --- | --- |
| DHS HQ | Blue Campaign | BC-dark-blue | `#003865` | 0, 56, 101 | 100, 83, 35, 23 | 2955 C |
| DHS HQ | Blue Campaign | BC-light-blue | `#0077c8` | 0, 119, 200 | 100, 35, 0, 2 | 3005 C |
| DHS HQ | See Something, Say Something® | SeeSay-blue | `#69b3e7` | 105, 179, 231 | 49, 11, 0, 0 | 292 C |
| CBP | U.S. Border Patrol | OBP-green | `#33460d` | 51, 70, 13 | 33, 0, 85, 82 | 5747 C |
| CBP | U.S. Border Patrol | OBP-blue | `#002b54` | 0, 43, 84 | 100, 49, 0, 70 | 295 C |
| CBP | U.S. Border Patrol | OBP-gold | `#fec057` | 254, 192, 87 | 0, 27, 76, 0 | 135 C |
| CBP | Air and Marine | AM-tan | `#cfab7a` | 207, 171, 122 | 20, 32, 58, 0 | 4022 C |
| CBP | Air and Marine | AM-light-brown | `#8b5625` | 139, 86, 37 | 34, 65, 98, 26 | 464 C |
| CBP | Air and Marine | AM-dark-brown | `#392713` | 57, 39, 19 | 54, 67, 84, 69 | 7533 C |
| USCG | Coast Guard | CG-Blue | `#006ba6` | 0, 107, 166 | 91, 56, 11, 1 | 307 C |
| USCG | Coast Guard | CG-Red | `#e03c31` | 224, 60, 49 | 6, 92, 91, 1 | 179 C |
| FEMA | Disaster Assistance | DA-dark-gold | `#ffbe2e` | 255, 190, 46 | 0, 29, 95, 0 | 123 C |
| FEMA | Disaster Assistance | DA-light-gold | `#faf3d1` | 250, 243, 209 | 1, 2, 21, 0 | 7506 C |
| FEMA | Ready.gov | Ready-green | `#339900` | 51, 153, 0 | 64, 5, 100, 24 | 2424 C |
| FEMA | Ready.gov | Ready-light-green | `#B6CD9E` | 182, 205, 158 | 22, 0, 40, 11 | 579 C |
| FEMA | Ready.gov | Ready-gray | `#666666` | 102, 102, 102 | 0, 0, 0, 60 | 4195 C |
| USSS | Secret Service | USSS-beast-black | `#010101` | 0, 0, 0 (see checks) | 75, 68, 67, 90 | Black C |
| USSS | Secret Service | USSS-lincoln-blue | `#002d61` | 0, 45, 97 | 100, 69, 0, 56 | 648 C |
| USSS | Secret Service | USSS-centurion-gold | `#b4a471` | 193, 168, 113 (see checks) | 20, 22, 59, 10 | 4515 C |
| USSS | Secret Service (secondary/highlight) | USSS-detail-blue | `#5f88b0` | 95, 136, 176 | 67, 40, 15, 1 | 646 C |
| USSS | Secret Service (secondary/highlight) | USSS-legacy-gold | `#d5cca8` | 213, 204, 168 | 12, 11, 36, 0 | 4545 C |
| TSA | TSA | TSA-orange | `#f7941d` | 247, 128, 29 (see checks) | 0, 50, 100, 0 | 1495 C |
| U.S. Government | Official colors | Old Glory Blue | `#002868` | 0, 40, 104 | 100, 92, 32, 23 | 280 C |
| U.S. Government | Official colors | Old Glory Red | `#bf0a30` | 191, 10, 48 | 17, 100, 86, 7 | 200 C |

## Checks on the source (2026-11-12)

* Every HTML value of the 60 gradient colors (and black and white) was converted to RGB and matches the published
  RGB exactly.
* Three restricted colors do not match; they are copied as published, not corrected. Confirm with the owner before
  using them:
  * USSS-beast-black: `#010101` is RGB 1, 1, 1; published RGB is 0, 0, 0.
  * USSS-centurion-gold: `#b4a471` is RGB 180, 164, 113; published RGB 193, 168, 113 would be `#c1a871`.
  * TSA-orange: `#f7941d` is RGB 247, 148, 29; published RGB 247, 128, 29 would be `#f7801d`.

## Contrast of common pairings (WCAG 2 formula, computed 2026-11-12)

The Section 508 minimum here is 4.5:1 for text and other foreground content.

| Foreground | Background | Ratio | Meets 4.5:1 |
| --- | --- | --- | --- |
| dhs-blue `#005288` | white | 8.20 | Yes |
| dhs-light-blue `#0078ae` | white | 4.89 | Yes |
| dhs-dark-gray `#5a5b5d` | white | 6.80 | Yes |
| dhs-red `#c41230` | white | 6.04 | Yes |
| dhs-green `#5e9732` | white | 3.53 | No |
| dhs-gray `#c0c2c4` | white | 1.79 | No |
| dhs-dark-gray-70 `#2f2f30` | dhs-blue-20 `#b8cfde` | 8.29 | Yes |
| dhs-dark-gray-70 `#2f2f30` | dhs-light-blue-20 `#b8d9e8` | 9.00 | Yes |
| dhs-dark-gray-70 `#2f2f30` | dhs-green-20 `#d2e2c6` | 9.83 | Yes |
| dhs-dark-gray-70 `#2f2f30` | dhs-red-20 `#eebdc5` | 8.10 | Yes |
| dhs-dark-gray-70 `#2f2f30` | dhs-blue-10 `#f5f8fa` | 12.54 | Yes |
| dhs-red `#c41230` | dhs-blue-15 `#d6e3ec` | 4.62 | Yes |
| dhs-red `#c41230` | dhs-blue-10 `#f5f8fa` | 5.66 | Yes |

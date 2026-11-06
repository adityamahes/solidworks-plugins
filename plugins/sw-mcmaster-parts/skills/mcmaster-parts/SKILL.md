---
name: mcmaster-parts
description: Find McMaster-Carr hardware (screws, nuts, bearings, dowel pins, shafts, shaft collars, standoffs, inserts, springs) with the McMaster MCP, download the native SolidWorks CAD (.SLDPRT) or STEP, file it in the project, and open it or insert it into the active SolidWorks assembly. Use when the user asks for McMaster parts, off-the-shelf hardware CAD, a bill of materials of purchased parts, or to "add bearings/screws" to a SolidWorks model, including the bearings and pins called out by the gearbox plugins.
---

# McMaster-Carr CAD parts for SolidWorks

Uses the **mcmaster** MCP server (tools `mcp__mcmaster__*`) for search, and
`scripts/mcmaster_cad.py` in this skill's base directory for files and SolidWorks.

## Requirements
- The mcmaster MCP server connected (check with `mcmaster_doctor` if unsure).
- Windows Python; `pywin32` and SolidWorks for `--open` / `--insert`. Find the interpreter as in the gyroid-lattice skill.

## Workflow
1. **Find the part.**
   - Full spec given ("M3 x 10 socket head cap screw, black oxide"): `mcmaster_find_exact_part`
     with the description. It returns one part only when the specs pin it down.
   - Looser request: `mcmaster_find_parts` (or `mcmaster_search`), then `mcmaster_extract_schema`
     to see the family's filters and columns and narrow it down with the user.
   - Gearbox hardware: turn the design report into specs. For example, a bearing "6805 (25x37x7)" becomes
     "6805 ball bearing 25 mm ID 37 mm OD 7 mm wide", and a 5 mm output pin becomes "5 mm dowel pin, length ≥ stack height".
2. **Confirm with the user** before downloading: part number, description, quantity, and file type. Downloading is the user's call.
3. **Get the CAD link.** `mcmaster_open` with the part number. In `links`, take the entry whose `text`
   is "Download" and whose URL ends in `.SLDPRT` (or `.STEP`). Never use a link from anywhere else.
4. **Fetch:**
   `python scripts/mcmaster_cad.py fetch --url "<Download URL>" --part <PN> --dir <project>/cad/mcmaster [--open | --insert --at X Y Z --count N --spacing DX DY DZ]`
   - The script only accepts `https://www.mcmaster.com` CAD URLs and caches by part number.
   - McMaster's CDN usually refuses non-browser clients. Then the script prints `BROWSER_REQUIRED` and exits
     with code 3. Ask the user to open the printed URL in their browser (it downloads to ~/Downloads), or open it
     yourself in a browser tool if they agree. Then run
     `python scripts/mcmaster_cad.py collect --part <PN> --dir <project>/cad/mcmaster [--open | --insert ...]`,
     which moves the newest matching download (last 30 min) into the project.
5. **Into SolidWorks:** `--open` opens the part; `--insert` adds it to the *active* assembly at the given mm
   position (repeat with `--count/--spacing` for patterns). Remind the user to add mates; parts come in floating.
6. `python scripts/mcmaster_cad.py bom --dir <project>/cad/mcmaster` lists every fetched part with its
   page link, which serves as the purchased-parts BOM.

## Rules
- Never enter McMaster login details, order, or add to cart. This skill only reads the catalog and pulls CAD.
- McMaster's own SolidWorks Add-In (mcmaster.com/solidworksaddin) is an alternative if the user prefers it.

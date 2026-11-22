"""lancelot-client: test suite and try-it client for the mcp-lancelot-beta MCP server."""

from __future__ import annotations

import base64
import json
import os
import time

import streamlit as st

from client import mcp_client as mc
from client import runner, storage, suite

st.set_page_config(page_title="lancelot-client", layout="wide")

MAX_FILE_BYTES = 14 * 1024 * 1024  # also enforced before upload by STREAMLIT_SERVER_MAX_UPLOAD_SIZE in app.yaml
MAX_TEXT_CHARS = 4_000_000  # pasted text cap; keeps the request well under the server's 20 MB body limit
AUTH_RECHECK_S = 300  # reuse the auth decision for this long between page reruns (code review L2)
DATA_RULE = ("Data rule: the server runs at APP_TRACE_LEVEL=debug and keeps copies of documents. "
             "Only send synthetic or public documents (for example the Pokemon samples). "
             "Never upload real, sensitive, or DHS documents.")
DIAGRAM_TYPES = ["(automatic)", "Flowchart", "Sequence diagram", "ERD", "Gantt", "State diagram",
                 "Class diagram", "Timeline", "Pie chart", "Mindmap (unsupported: falls back)"]
VERDICT_ICON = {"PASS": ":green[PASS]", "FAIL": ":red[FAIL]", "INFO": ":blue[INFO]", "SKIP": ":gray[SKIP]"}


def get_auth(fresh: bool = False):
    """Resolve auth (Mode A first, else Mode B). Tokens stay in memory only.

    Code review L2: the token-free decision (mode, note, finding) is cached in the session for
    AUTH_RECHECK_S, so ordinary page reruns do not probe /health again. fresh=True (used when a
    suite or try-it run starts, and by the Re-check button) always resolves from scratch, so
    every report records a current finding."""
    force_b = bool(st.session_state.get("force_mode_b", False))
    cached = st.session_state.get("auth_decision")
    if (not fresh and cached and cached["forceModeB"] == force_b
            and time.monotonic() - cached["at"] < AUTH_RECHECK_S):
        auth = mc.reuse_auth(st.context.headers, cached)
        if auth is not None:
            return auth, cached["finding"]
    auth, finding = mc.resolve_auth(st.context.headers, force_mode_b=force_b)
    st.session_state["auth_decision"] = {"mode": auth.mode if auth else None, "note": auth.note if auth else None,
                                         "forceModeB": force_b, "at": time.monotonic(), "finding": finding}
    return auth, finding


def auth_banner(auth, finding):
    if auth is None:
        st.error("No usable credentials: no user token was forwarded and the service principal token failed. "
                 f"{finding.get('modeBError')}")
        return
    if auth.mode == mc.MODE_A:
        st.success(f"Auth mode A (signed-in user {auth.caller_email}). {auth.note}")
    else:
        st.warning(f"Auth mode B (app service principal {auth.sp_application_id}). {auth.note}")
    if finding.get("modeARejected"):
        st.error("Finding: the server rejected the forwarded user token "
                 f"(/health {json.dumps(finding.get('modeAHealth'))}). Recorded in every report.")


def page_connection():
    st.header("Connection")
    auth, finding = get_auth(fresh=st.button("Re-check auth now"))
    auth_banner(auth, finding)
    st.write(f"Server: `{mc.SERVER_BASE}`  |  MCP endpoint: `{mc.MCP_URL}`")
    st.write(f"Client service principal: `{os.environ.get('DATABRICKS_CLIENT_ID', 'unknown')}` "
             "(needs CAN_USE on mcp-lancelot-beta for Mode B)")
    if auth and st.button("Check /health and /api/selftest-obo-scope"):
        for path in ("/health", "/api/selftest-obo-scope"):
            r = mc.http_get(path, auth.token)
            st.subheader(path)
            st.json({k: v for k, v in r.items() if k != "bodySnippet"} | ({"bodySnippet": r["bodySnippet"]}
                                                                        if r.get("bodySnippet") else {}))
    with st.expander("Auth finding (token-free)"):
        st.json(finding)
    with st.expander("Library versions"):
        st.json(runner.versions())


def show_storage(res):
    errs = res["storage"]["errors"]
    if errs:
        st.error(f"Storage errors ({len(errs)}). Test results are unaffected.")
        st.json(errs)
    else:
        st.info(f"Results written to `{res['storage']['runDir']}/`")


def page_suite():
    st.header("Test suite")
    st.caption("Runs C1-C3, V4-V12, V14, M1-M6 and T1 sequentially against mcp-lancelot-beta. "
               "Expect up to about 10 minutes. Keep this tab open while it runs.")
    missing = [n for n in ("sample.pdf", "sample.docx", "sample.xlsx", "sample.json") if runner.load_sample(n) is None]
    if missing:
        st.warning(f"Missing samples in samples/: {', '.join(missing)}. Cases that need them will FAIL.")
    auth, finding = get_auth()
    auth_banner(auth, finding)
    if auth is None or not st.button("Run test suite", type="primary"):
        last = st.session_state.get("last_suite")
        if last:
            render_suite(*last)
        return
    auth, finding = get_auth(fresh=True)  # every report records a current auth finding
    if auth is None:
        st.error("No usable credentials at run start. " + str(finding.get("modeBError")))
        return
    store = storage.Storage()
    total = len(suite.CASES)
    bar = st.progress(0.0, text="Starting")
    log = st.container()

    def on_start(i, cid, title):
        bar.progress((i - 1) / total, text=f"{i}/{total} running {cid}: {title}")

    def on_case(i, rec):
        log.markdown(f"{VERDICT_ICON.get(rec['verdict'], rec['verdict'])} **{rec['id']}** {rec['title']} "
                     f"({rec.get('clientMs')} ms): {rec.get('actual')}")

    res, pngs, widgets = runner.run_suite(auth, finding, store, on_start=on_start, on_case=on_case)
    bar.progress(1.0, text="Done")
    st.session_state["last_suite"] = (res, pngs, widgets)
    render_suite(res, pngs, widgets)


WIDGET_HEIGHT_PX = 1100  # fixed: the map page changes height as views switch; the frame scrolls if needed
WIDGET_NOTE = ("This is the HTML the server returned for this call, shown as-is. Try the category buttons, "
               "hover and zoom, then rate it below. Feedback is saved next to this run's result.json.")


def render_widgets(res, widgets):
    """D19: the generate_choropleth widgets, inline, each with a feedback form."""
    cases = [c for c in res["cases"] if c["id"] in widgets]
    if not cases:
        return
    st.subheader("Interactive maps (generate_choropleth)")
    st.caption(WIDGET_NOTE)
    reviewer = (res.get("auth") or {}).get("callerEmail")
    for c in cases:
        w = c.get("widget") or {}
        st.markdown(f"{VERDICT_ICON.get(c['verdict'], c['verdict'])} **{c['id']}** {c['title']}: "
                    f"{c.get('actual')}")
        # The widget is this server's own output (no LLM in this tool; data text is set with textContent)
        # and carries its own CSP with default-src 'none', so it makes no network requests.
        st.iframe(widgets[c["id"]], height=WIDGET_HEIGHT_PX, alt=f"{c['id']} interactive county map")
        st.caption(f"{w.get('bytes')} bytes, sha256 {w.get('sha256')}, file {w.get('file') or '(not written)'} "
                   f"in {res['storage']['runDir']}")
        feedback_form(res, c, reviewer)
        st.divider()


def feedback_form(res, c, reviewer, label=None):
    """Rating + comment for one map, saved next to that run's result.json (D19)."""
    key = f"{res['clientRunId']}-{c['id']}"
    with st.form(key=f"feedback-{key}", clear_on_submit=True):
        rating = st.radio("How did it work?", runner.FEEDBACK_RATINGS, horizontal=True, index=None, key=f"rating-{key}")
        comment = st.text_area("Comments (what you tried, what looked wrong, what you expected)",
                               max_chars=runner.FEEDBACK_MAX_CHARS, key=f"comment-{key}")
        if st.form_submit_button(label or f"Save feedback on {c['id']}"):
            if rating is None:
                st.warning("Pick a rating first.")
            else:
                path = runner.save_feedback(storage.Storage(), res, c, rating, comment, reviewer)
                if path:
                    st.success(f"Saved: {path}")
                else:
                    st.error("Could not save feedback to the trace volume.")


def render_suite(res, pngs, widgets=None):
    widgets = widgets or {}
    s = res["summary"]
    st.subheader(f"Run {res['clientRunId']} ({res['auth'].get('mode')})")
    cols = st.columns(4)
    for col, k in zip(cols, ("PASS", "FAIL", "INFO", "SKIP")):
        col.metric(k, s.get(k, 0))
    show_storage(res)
    st.dataframe([{"id": c["id"], "verdict": c["verdict"], "case": c["title"], "ms": c.get("clientMs"),
                   "serverRunId": c.get("serverRunId"), "actual": c.get("actual")} for c in res["cases"]],
                 width="stretch", hide_index=True)
    render_widgets(res, widgets)
    for c in res["cases"]:
        with st.expander(f"{c['id']} {c['title']}: {c['verdict']}"):
            if c.get("note"):
                st.caption(c["note"])
            if c["id"] in pngs:
                st.image(pngs[c["id"]])
            st.json(c)


# Disasters checked against the 2026-11-06 data (server D42/D43 smoke runs); each exercises a
# different part of the map. Any loaded disaster number can be typed in instead.
FEMA_PRESETS = [
    (4856, "CA", "few outliers (5); highlight with PW 2"),
    (4673, "FL", "many outliers (47), 17 in Lee County: dots crowd at zoom 1"),
    (4611, "LA", "parishes, many outliers (49)"),
    (4671, "PR", "Puerto Rico municipios, many outliers (51)"),
    (4580, "CT", "Connecticut's old counties (2021 shapes)"),
    (4585, "AK", "obsolete FEMA code 02232 drawn as Hoonah-Angoon 02105; unmappable projects"),
    (4730, "AK", "Valdez-Cordova 02261 merged from 02063 + 02066; 46 unmappable projects"),
]
FEMA_OTHER = "Other (type a number)"
FEMA_HISTORY = 10


# Server D46: choropleth map display options. NOT_SENT leaves the option out, so the server default applies.
NOT_SENT = "(not sent: server default)"
DISPLAY_OPTIONS = [  # (argument, choices after NOT_SENT, help)
    ("initial_view", ["pw_category", "all"], "Filter the map opens on. Default pw_category (the PW's category, or All)."),
    ("show_pause_button", [True, False], "Pause/Play button for the outlier pulse. Default true."),
    ("show_pw_card", [True, False], "The 'PW <number>' summary card. Default true; the PW stays highlighted either way."),
    ("show_all_categories_card", [True, False], "The 'All categories A-G' summary card. Default true."),
    ("legend_position", ["below_cards", "below_map"], "Where the legend sits. Default below_cards."),
    ("click_details", ["none", "modal"], "modal: clicking a dot or county opens a details window. Default none."),
]
# Server D50: map box shape (width:height). Its own control, not part of the presets; this client
# sends 16:9 unless changed (for testing). NOT_SENT = the box follows the state's shape.
MAP_ASPECT_RATIOS = ["1:1", "16:9", "4:3", "5:3", "9:16", "3:4", "3:5"]
MAP_ASPECT_RATIO_DEFAULT = "16:9"
DISPLAY_PRESETS = {
    "Server defaults": {},
    "FEMA Pulse": {"initial_view": "all", "show_pause_button": False, "show_pw_card": False,
                   "show_all_categories_card": False, "legend_position": "below_map", "click_details": "modal"},
    "Custom": None,
}


def display_options():
    """The display arguments chosen on the Try It - FEMA page (only the ones to send): the six D46
    options from the preset, plus map_aspect_ratio (D50), which has its own control."""
    st.markdown("**Choropleth map display options**")
    preset = st.radio("Display preset", list(DISPLAY_PRESETS), horizontal=True,
                      help="For the six options below. Server defaults = send none of them. FEMA Pulse = the "
                           "options FEMA Pulse sends. Custom = pick each one. map_aspect_ratio is set separately.")
    fixed = DISPLAY_PRESETS[preset]
    cols = st.columns(3)
    chosen = {}
    for i, (name, choices, why) in enumerate(DISPLAY_OPTIONS):
        options = [NOT_SENT] + choices
        index = options.index(fixed[name]) if fixed and name in fixed else 0
        v = cols[i % 3].selectbox(name, options, index=index, help=why, disabled=fixed is not None,
                                  format_func=lambda o: json.dumps(o) if isinstance(o, bool) else str(o),
                                  key=f"display-{name}-{preset}")
        if v != NOT_SENT:
            chosen[name] = v
    ratios = [NOT_SENT] + MAP_ASPECT_RATIOS
    ratio = st.selectbox("map_aspect_ratio", ratios, index=ratios.index(MAP_ASPECT_RATIO_DEFAULT), key="display-map_aspect_ratio",
                         help="Shape of the map box, width:height; the whole state is fitted inside it. Not part of "
                              "the presets. This client sends 16:9 by default for testing; 'not sent' = the box "
                              "follows the state's shape (server default).")
    if ratio != NOT_SENT:
        chosen["map_aspect_ratio"] = ratio
    return chosen


def fema_args(disaster, pw, applicant, sigma_on, sigma, as_of, numbers_as_strings, display=None):
    """Arguments for generate_choropleth from the form. Empty optional fields are not sent, so the
    server's defaults apply. display: the D46 options to send (booleans as "true"/"false" when
    numbers_as_strings is on, like a client that sends every value as a string)."""
    def num(v):
        return str(v) if numbers_as_strings else v

    args = {"disaster_number": num(disaster)}
    if pw.strip():
        p = pw.strip()
        args["pw_number"] = p if numbers_as_strings or not p.isdigit() else int(p)
    if applicant.strip():
        args["applicant_id"] = applicant.strip()
    if sigma_on:
        args["sigma_threshold"] = num(sigma)
    if as_of.strip():
        args["as_of"] = as_of.strip()
    for k, v in (display or {}).items():
        args[k] = ("true" if v else "false") if isinstance(v, bool) and numbers_as_strings else v
    return args


def page_try_fema():
    st.header("Try It - FEMA: generate_choropleth")
    st.caption("Calls the map tool once with your inputs and shows the interactive HTML it returns, so you can "
               "test a change without running the whole suite. Uses public OpenFEMA data; no LLM. "
               "Each try is saved as its own run (result.json, TRY.widget.html) on the trace volume.")
    auth, finding = get_auth()
    auth_banner(auth, finding)

    labels = [f"DR-{n} ({s}): {why}" for n, s, why in FEMA_PRESETS] + [FEMA_OTHER]
    pick = st.selectbox("Disaster", labels)
    if pick == FEMA_OTHER:
        disaster = st.number_input("disaster_number", min_value=1, max_value=99999, value=4856, step=1)
    else:
        disaster = FEMA_PRESETS[labels.index(pick)][0]
    c1, c2 = st.columns(2)
    pw = c1.text_input("pw_number (optional): PW to highlight", help="The map opens on that PW's category.")
    applicant = c2.text_input("applicant_id (optional)", help="Only needed when the PW number exists for more "
                                                             "than one applicant, e.g. 000-UDQ5V-00.")
    c3, c4 = st.columns(2)
    sigma_on = c3.checkbox("Send sigma_threshold", value=False, help="Off: the server default (3) applies.")
    sigma = c3.slider("sigma_threshold", min_value=1.0, max_value=10.0, value=3.0, step=0.5, disabled=not sigma_on)
    as_of = c4.text_input("as_of (optional, YYYY-MM-DD)", help="Snapshot date; empty means the latest.")
    numbers_as_strings = c4.checkbox("Send numbers as strings", value=False,
                                     help="Some MCP clients send \"4856\" instead of 4856; the server accepts both.")
    display = display_options()
    args = fema_args(disaster, pw, applicant, sigma_on, sigma, as_of, numbers_as_strings, display)
    with st.expander("Arguments sent (edit to test invalid input)"):
        raw = st.text_area("JSON object", value=json.dumps(args), key=f"fema-raw-{json.dumps(args)}")
        try:
            edited = json.loads(raw)
            if not isinstance(edited, dict):
                raise ValueError("not a JSON object")
            args = edited
        except ValueError as e:
            st.error(f"Not valid: {e}. The form values above will be sent.")
    if auth is not None and st.button("Generate map", type="primary"):
        auth, finding = get_auth(fresh=True)
        if auth is None:
            st.error("No usable credentials at run start. " + str(finding.get("modeBError")))
            return
        with st.spinner("Calling generate_choropleth"):
            result = runner.try_fema(auth, finding, storage.Storage(), args)
        hist = st.session_state.setdefault("fema_history", [])
        hist.insert(0, result)
        del hist[FEMA_HISTORY:]
        st.session_state["fema_shown"] = 0

    hist = st.session_state.get("fema_history") or []
    if not hist:
        return
    st.divider()
    if len(hist) > 1:
        names = [f"{h['res']['clientRunId']}: {json.dumps(h['rec'].get('arguments'))} -> {h['rec']['verdict']}" for h in hist]
        shown = st.selectbox("Show try", range(len(hist)), format_func=lambda i: names[i],
                             index=min(st.session_state.get("fema_shown", 0), len(hist) - 1))
    else:
        shown = 0
    show_fema(hist[shown])


def show_fema(h):
    res, rec, html = h["res"], h["rec"], h["html"]
    st.markdown(f"{VERDICT_ICON.get(rec['verdict'], rec['verdict'])} {rec.get('actual')}")
    for t in h.get("texts") or []:
        st.info(t)
    message = rec.get("message") or (h.get("meta") or {}).get("message")  # page only; not stored for every code
    if rec.get("mcpIsError") and message:
        st.warning(f"{rec.get('errorCode')} at stage {rec.get('stage')}: {message}")
    if rec.get("transportError"):
        st.error(rec["transportError"])
    if html is not None:
        c1, c2 = st.columns([3, 1])
        height = c2.slider("Frame height (px)", 500, 2000, WIDGET_HEIGHT_PX, 50, key=f"h-{res['clientRunId']}")
        c1.caption("Try every category button, hover counties and dots, zoom and pan, and the highlighted PW."
                   + (" click_details modal: click dots and counties; close with X, Escape or a click outside."
                      if str((rec.get("arguments") or {}).get("click_details", "")).lower() == "modal" else ""))
        st.iframe(html, height=height, alt="generate_choropleth interactive county map")
        w = rec.get("widget") or {}
        st.download_button("Download this HTML", html.encode("utf-8"), file_name=f"{res['clientRunId']}.html",
                           mime="text/html", help="Open it on its own in a browser tab.")
        st.caption(f"{w.get('bytes')} bytes, sha256 {w.get('sha256')}, CSP {w.get('csp')}, external URLs "
                   f"{len(w.get('externalUrls') or [])}; saved as {res['storage']['runDir']}/{w.get('file') or '(not written)'}")
    png = h.get("png")
    if png:
        im = rec.get("image") or {}
        st.subheader("Square image (PNG)")
        st.image(png, width=500, caption=im.get("title"))
        st.download_button("Download this PNG", png, file_name=f"{res['clientRunId']}.png", mime="image/png")
        st.caption(f"{im.get('width')}x{im.get('height')}, {im.get('bytes')} bytes, sha256 matches structuredContent: "
                   f"{im.get('shaMatches')}; map drawn {im.get('mapDrawn')}"
                   + (f" ({im.get('reason')})" if im.get("reason") else f", {im.get('affectedDrawn')} affected counties"))
    elif (rec.get("image") or {}).get("error"):
        st.warning(f"No square image: {rec['image']['error']}")
    with st.expander("Result checks (as recorded)"):
        st.json({k: rec.get(k) for k in ("arguments", "choropleth", "widget", "image", "errorCode", "stage", "serverRunId",
                                         "clientMs", "callMs", "serverTrace")})
    if h.get("structured"):
        with st.expander("structuredContent (what an MCP client gets besides the HTML)"):
            st.json(h["structured"])
    show_storage(res)
    if html is not None:
        st.subheader("Feedback on this map")
        feedback_form(res, rec, (res.get("auth") or {}).get("callerEmail"), label="Save feedback")


def page_try():
    st.header("Try It - Mermaid: generate_diagram")
    st.warning(DATA_RULE)
    auth, finding = get_auth()
    auth_banner(auth, finding)
    source = st.radio("Input", ["Sample", "Paste text", "Upload file"], horizontal=True)
    args, inputs = {}, []
    if source == "Sample":
        names = runner.list_samples()
        if not names:
            st.error("No files in samples/.")
        else:
            name = st.selectbox("Sample", names)
            data = runner.load_sample(name) or b""
            if name.lower().endswith((".txt", ".md", ".csv", ".yaml", ".yml")) or (
                    name.lower().endswith(".json") and name.startswith("synthetic")):
                args = {"data": data.decode("utf-8", errors="replace")}
                inputs = [suite.input_desc("data", name, data)]
            else:
                args = {"fileBase64": base64.b64encode(data).decode("ascii"), "fileName": name}
                inputs = [suite.input_desc("fileBase64", name, data)]
    elif source == "Paste text":
        text = st.text_area("Text, JSON, CSV, YAML or Markdown (synthetic or public only)", height=220,
                            max_chars=MAX_TEXT_CHARS)
        if text.strip():
            b = text.encode("utf-8")
            args, inputs = {"data": text}, [suite.input_desc("data", None, b)]
    else:
        up = st.file_uploader("File (PDF, DOCX, XLSX, HTML, CSV, JSON, YAML, TXT, MD; max 14 MB). " + DATA_RULE,
                              type=["pdf", "docx", "xlsx", "html", "htm", "csv", "json", "yaml", "yml", "txt", "md"])
        if up is not None:
            b = up.getvalue()
            if len(b) > MAX_FILE_BYTES:
                st.error(f"File is {len(b):,} bytes; the server limit is 14 MB.")
            else:
                args = {"fileBase64": base64.b64encode(b).decode("ascii"), "fileName": up.name}
                inputs = [suite.input_desc("fileBase64", up.name, b)]
    c1, c2 = st.columns(2)
    dt = c1.selectbox("diagramType", DIAGRAM_TYPES)
    hint = c2.text_input("hint (optional, one line)")
    if args:
        if dt != "(automatic)":
            args["diagramType"] = dt.split(" (")[0]
        if hint.strip():
            args["hint"] = hint.strip()
    if auth is None or not st.button("Generate diagram", type="primary", disabled=not args):
        return
    auth, finding = get_auth(fresh=True)
    if auth is None:
        st.error("No usable credentials at run start. " + str(finding.get("modeBError")))
        return
    store = storage.Storage()
    with st.spinner("Calling generate_diagram (can take up to ~70 s)"):
        res, rec, png, meta = runner.try_it(auth, finding, store, args, inputs)
    st.markdown(f"{VERDICT_ICON.get(rec['verdict'])} {rec['actual']}")
    if png:
        st.image(png)
    if meta:
        if meta.get("mermaidSource"):
            with st.expander("Mermaid source"):
                st.code(meta["mermaidSource"], language="text")
        st.json({k: v for k, v in meta.items() if k != "mermaidSource"})
    if rec.get("transportError"):
        st.error(rec["transportError"])
    if rec.get("serverTrace"):
        st.caption(f"Server trace: {json.dumps(rec['serverTrace'])}")
    show_storage(res)


PAGES = {"Test suite": page_suite, "Try It - Mermaid": page_try, "Try It - FEMA": page_try_fema,
         "Connection": page_connection}
choice = st.sidebar.radio("lancelot-client", list(PAGES))
st.sidebar.toggle("Force Mode B (service principal)", key="force_mode_b",
                  help="Skip the signed-in user token and call the server as this app's service principal. "
                       "Applies to every page in this browser session and is recorded in each report.")
st.sidebar.caption("Client for mcp-lancelot-beta. Results go to "
                   f"{storage.CLIENT_ROOT}/<date>/<clientRunId>/")
PAGES[choice]()

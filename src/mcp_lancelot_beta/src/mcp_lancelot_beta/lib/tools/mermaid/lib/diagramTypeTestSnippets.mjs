// Minimal, hand-picked Mermaid source for EVERY entry in lib/prompts.mjs's
// DIAGRAM_CATALOG (including entries already in UNSUPPORTED_DIAGRAM_TYPES -
// those are deliberately kept here too, so the gallery route in server.mjs
// re-confirms them on every run instead of just trusting a stale registry
// entry forever). Each snippet is copied/trimmed directly from that type's
// own PROMPTS/*.md syntax guide (the same source of truth
// buildDiagramSyntaxPrompt() uses for the real LLM-facing instructions) so
// these are known-valid syntax for the installed mermaid version (11.17.2),
// not guessed from general Mermaid knowledge that might be stale for the
// many `-beta` types here. Deliberately kept tiny (a handful of
// nodes/lines) - the goal is only "does this diagram type render AT ALL in
// this jsdom+resvg environment", not exercising every syntax feature.
//
// Keyed by the exact `name` string used in DIAGRAM_CATALOG so the gallery
// route can look each one up directly.
export const DIAGRAM_TYPE_TEST_SNIPPETS = {
  Agentflow: `agentflow-beta TB
  flow reviewer["Review Agent"]
    changes["Gather changes"]@{ shape: input }
    analyse["Analyse diff"]@{ shape: task }
    changes --> analyse
  end`,
  Architecture: `architecture-beta
    group api(cloud)[API]
    service db(database)[Database] in api
    service disk1(disk)[Storage] in api
    db:L -- R:disk1`,
  'Block diagram': `block
columns 1
  A
  B["A wide one"]
  A --> B`,
  C4: `C4Context
    title System Context diagram
    Person(customerA, "Customer A", "A customer.")
    System(SystemAA, "Banking System", "Allows customers to view accounts.")
    Rel(customerA, SystemAA, "Uses")`,
  'Class diagram': `classDiagram
    Animal <|-- Duck
    Animal : +int age
    Animal: +isMammal()`,
  Cynefin: `cynefin-beta
title Test
clear
"Known procedure"
complex
"Item label"`,
  ERD: `erDiagram
    CUSTOMER ||--o{ ORDER : places`,
  'Event Modeling': `eventmodeling

tf 01 ui CartUI
tf 02 cmd AddItem
tf 03 evt ItemAdded`,
  Flowchart: `flowchart LR
    A --> B`,
  Gantt: `gantt
    title A Gantt Diagram
    dateFormat YYYY-MM-DD
    section Section
    A task           :a1, 2024-01-01, 5d
    Another task     :after a1, 3d`,
  GitGraph: `gitGraph
    commit
    branch develop
    checkout develop
    commit
    checkout main
    merge develop`,
  'Ishikawa/Fishbone': `ishikawa-beta
    Problem
    Cause A
        Sub cause
    Cause B`,
  Kanban: `kanban
  column1[Todo]
    task1[Task Description]`,
  Mindmap: `mindmap
  root((mindmap))
    Origins
    Tools`,
  'Packet diagram': `packet
0-15: "Source Port"
16-31: "Destination Port"`,
  'Pie/Donut': `pie title Pets adopted
    "Dogs" : 386
    "Cats" : 85`,
  'Quadrant chart': `quadrantChart
    title Reach and engagement
    x-axis Low Reach --> High Reach
    y-axis Low Engagement --> High Engagement
    quadrant-1 We should expand
    quadrant-2 Need to promote
    quadrant-3 Re-evaluate
    quadrant-4 May be improved
    Campaign A: [0.3, 0.6]`,
  Radar: `radar-beta
  axis m["Math"], s["Science"], e["English"]
  curve a["Alice"]{85, 90, 80}
  max 100
  min 0`,
  Railroad: `railroad-ebnf-beta
title "Digit Definition"
digit = "0" | "1" | "2" ;`,
  'Requirement diagram': `requirementDiagram
    requirement test_req {
    id: 1
    text: the test text.
    risk: high
    verifymethod: test
    }
    element test_entity {
    type: simulation
    }
    test_entity - satisfies -> test_req`,
  Sankey: `sankey

A,B,10
B,C,5`,
  'Sequence diagram': `sequenceDiagram
    Alice->>John: Hello John, how are you?
    John-->>Alice: Great!`,
  'State diagram': `stateDiagram-v2
    [*] --> Still
    Still --> [*]`,
  Swimlanes: `swimlane-beta LR
  subgraph Customer
    request[Request service]
  end
  subgraph Support
    triage[Triage request]
  end
  request --> triage`,
  Timeline: `timeline
    title History
    2002 : LinkedIn
    2004 : Facebook`,
  TreeView: `treeView-beta
    my-project/
        src/
            index.js
        package.json`,
  Treemap: `treemap-beta
"Category A"
    "Item A1": 10
    "Item A2": 20`,
  'Use case': `usecase-beta
direction LR
actor Customer("Customer")
systemBoundary "Order system"
  Checkout("Place order")
end
Customer --> Checkout`,
  'User journey': `journey
    title My working day
    section Go to work
      Make tea: 5: Me`,
  Venn: `venn-beta
  title "Team overlap"
  set Frontend
  set Backend
  union Frontend,Backend["APIs"]`,
  'Wardley map': `wardley-beta
title Tea Shop Value Chain
anchor Business [0.95, 0.63]
component Cup of Tea [0.79, 0.61]
Business -> Cup of Tea`,
  'XY chart': `xychart
    title "Sales Revenue"
    x-axis [jan, feb, mar]
    y-axis "Revenue" 0 --> 10000
    bar [5000, 6000, 7500]`,
};

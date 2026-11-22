# Gantt diagrams

> A Gantt chart is a type of bar chart that illustrates a project schedule. It shows the dependency relationships between activities and the current schedule status.

Mermaid can render Gantt diagrams.

```mermaid-example
gantt
    title A Gantt Diagram
    dateFormat YYYY-MM-DD
    section Section
    A task           :a1, 2024-01-01, 30d
    Another task     :after a1, 20d
    section Another
    Task in sec      :2024-01-12, 12d
    another task     :24d
```

```mermaid
gantt
    title A Gantt Diagram
    dateFormat YYYY-MM-DD
    section Section
    A task           :a1, 2024-01-01, 30d
    Another task     :after a1, 20d
    section Another
    Task in sec      :2024-01-12, 12d
    another task     :24d
```

## Syntax

- Start with the `gantt` keyword.
- Optionally add a `title` line.
- Optionally set `dateFormat` (e.g. `YYYY-MM-DD`) to control how dates in task lines are parsed.
- Group tasks under `section <Section Name>` headers.
- Each task line follows: `Task name : [tag,] [id,] start, duration|end`.
  - `start` can be an explicit date, `after <taskId>`, or omitted to continue from the previous task.
  - `duration` is a number followed by a unit (`d` days, `w` weeks, `h` hours, `m` minutes).
  - Optional status tags before the id: `done`, `active`, `crit`, `milestone`.

```mermaid-example
gantt
    dateFormat  YYYY-MM-DD
    title       Adding GANTT diagram functionality to mermaid
    excludes    weekends
    section A section
    Completed task            :done,    des1, 2014-01-06,2014-01-08
    Active task               :active,  des2, 2014-01-09, 3d
    Future task                :         des3, after des2, 5d
    Future task2                :         des4, after des3, 5d
```

```mermaid
gantt
    dateFormat  YYYY-MM-DD
    title       Adding GANTT diagram functionality to mermaid
    excludes    weekends
    section A section
    Completed task            :done,    des1, 2014-01-06,2014-01-08
    Active task               :active,  des2, 2014-01-09, 3d
    Future task                :         des3, after des2, 5d
    Future task2                :         des4, after des3, 5d
```

"use client";

import { DndContext, KeyboardSensor, PointerSensor, closestCenter, useSensor, useSensors, type DragEndEvent } from "@dnd-kit/core";
import { SortableContext, arrayMove, sortableKeyboardCoordinates, useSortable, verticalListSortingStrategy } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { ArrowDown, ArrowUp, ChevronDown, ChevronRight, Copy, GripVertical, Plus, Trash2 } from "lucide-react";
import * as React from "react";
import useSWR from "swr";
import { MessageIcon, actionLabel, stepSummary } from "@/components/step-list";
import { Button, Input, Select, Textarea } from "@/components/ui";
import { fetcher } from "@/lib/api";
import type { Step, StepAction, ValidationMessage } from "@/lib/types";
import { cn } from "@/lib/utils";

type Row = Step & { _key: string };
let keySeq = 0;
const withKey = (s: Step): Row => ({ ...s, _key: `k${++keySeq}` });
const strip = ({ _key, ...s }: Row): Step => s; // eslint-disable-line @typescript-eslint/no-unused-vars

const GROUPS: { label: string; actions: string[] }[] = [
  { label: "Browser", actions: ["navigate", "click", "fill", "select", "check", "uncheck", "press", "wait_for", "wait_ms", "screenshot"] },
  { label: "Checks", actions: ["assert_visible", "assert_hidden", "assert_text", "assert_no_text", "assert_value", "assert_count", "assert_url", "assert_url_not", "assert_title"] },
  { label: "Data", actions: ["store_text", "set_variable", "api_request"] },
];

const STRATEGIES = [
  { value: "role", label: "Button, link or element (by role)" },
  { value: "label", label: "Form field (by label)" },
  { value: "text", label: "Visible text" },
  { value: "placeholder", label: "Placeholder text" },
  { value: "testid", label: "Test id" },
  { value: "css", label: "CSS selector (advanced)" },
];
const ROLES = ["button", "link", "heading", "textbox", "checkbox", "combobox", "tab", "menuitem", "alert", "status", "dialog", "row", "cell", "table", "img"];

function blankStep(action: string): Step {
  if (action === "api_request") return { action, target: null, value: null, options: { method: "GET", url: "{{api_base_url}}/", expect: { status: [200] } }, description: "" };
  if (action === "set_variable") return { action, target: null, value: "", options: { name: "" }, description: "" };
  return { action, target: null, value: null, options: {}, description: "" };
}

function TargetEditor({ step, onChange }: { step: Step; onChange: (s: Step) => void }) {
  const t = step.target ?? { strategy: "role", value: "button", name: "" };
  const set = (patch: Partial<typeof t>) => onChange({ ...step, target: { ...t, ...patch } });
  return (
    <div className="grid gap-2 sm:grid-cols-[minmax(0,15rem)_1fr]">
      <Select aria-label="How to find the element" value={t.strategy} onChange={(e) => {
        const strategy = e.target.value;
        onChange({ ...step, target: strategy === "role" ? { strategy, value: "button", name: t.name || t.value } : { strategy, value: t.strategy === "role" ? t.name || "" : t.value } });
      }}>
        {STRATEGIES.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
      </Select>
      {t.strategy === "role" ? (
        <div className="grid grid-cols-[8rem_1fr] gap-2">
          <Select aria-label="Element type" value={t.value} onChange={(e) => set({ value: e.target.value })}>{ROLES.map((r) => <option key={r}>{r}</option>)}</Select>
          <Input aria-label="Element name" value={t.name ?? ""} placeholder="Name shown on the page, e.g. Sign in" onChange={(e) => set({ name: e.target.value })} />
        </div>
      ) : (
        <Input aria-label="Locator value" value={t.value} placeholder={t.strategy === "label" ? "Field label, e.g. Email" : t.strategy === "css" ? "#submit" : "Text"} onChange={(e) => set({ value: e.target.value })} />
      )}
    </div>
  );
}

function JsonField({ label, value, onChange, rows = 3 }: { label: string; value: unknown; onChange: (v: unknown) => void; rows?: number }) {
  const [text, setText] = React.useState(value === undefined ? "" : JSON.stringify(value, null, 2));
  const [bad, setBad] = React.useState(false);
  return (
    <label className="grid gap-1 text-xs font-medium">{label}
      <Textarea rows={rows} className={cn("font-mono text-xs", bad && "border-destructive")} value={text}
        onChange={(e) => {
          setText(e.target.value);
          if (!e.target.value.trim()) { setBad(false); onChange(undefined); return; }
          try { onChange(JSON.parse(e.target.value)); setBad(false); } catch { setBad(true); }
        }} />
      {bad && <span className="font-normal text-destructive">Not valid JSON yet</span>}
    </label>
  );
}

function ApiEditor({ step, onChange }: { step: Step; onChange: (s: Step) => void }) {
  const o = step.options ?? {};
  const setO = (patch: Record<string, unknown>) => onChange({ ...step, options: { ...o, ...patch } });
  const exp = o.expect ?? {};
  return (
    <div className="grid gap-2">
      <div className="grid grid-cols-[7rem_1fr] gap-2">
        <Select aria-label="HTTP method" value={o.method ?? "GET"} onChange={(e) => setO({ method: e.target.value })}>{["GET", "POST", "PUT", "PATCH", "DELETE"].map((m) => <option key={m}>{m}</option>)}</Select>
        <Input aria-label="Request URL" value={o.url ?? ""} onChange={(e) => setO({ url: e.target.value })} className="font-mono text-xs" />
      </div>
      <div className="grid gap-2 sm:grid-cols-2">
        <JsonField label="Headers" value={o.headers} onChange={(v) => setO({ headers: v })} />
        <JsonField label="JSON body" value={o.body} onChange={(v) => setO({ body: v })} />
      </div>
      <div className="grid gap-2 sm:grid-cols-2">
        <label className="grid gap-1 text-xs font-medium">Expected status codes
          <Input value={(exp.status ?? []).join(", ")} placeholder="200, 201" onChange={(e) => setO({ expect: { ...exp, status: e.target.value.split(",").map((s) => Number(s.trim())).filter(Boolean) } })} />
        </label>
        <JsonField label="Save values from the response (variable: JSON path)" value={o.store} onChange={(v) => setO({ store: v })} rows={2} />
      </div>
      <JsonField label="Response JSON schema (optional)" value={exp.schema} onChange={(v) => setO({ expect: { ...exp, schema: v } })} rows={3} />
    </div>
  );
}

function StepRow({ row, index, total, actions, messages, open, setOpen, update, remove, duplicate, move, readOnly }: {
  row: Row; index: number; total: number; actions: Record<string, StepAction>; messages: ValidationMessage[]; open: boolean;
  setOpen: (o: boolean) => void; update: (s: Step) => void; remove: () => void; duplicate: () => void; move: (d: -1 | 1) => void; readOnly?: boolean;
}) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id: row._key, disabled: readOnly });
  const spec = actions[row.action];
  const errors = messages.filter((m) => m.step === index + 1 && m.level !== "info");
  return (
    <li ref={setNodeRef} style={{ transform: CSS.Transform.toString(transform), transition }}
      className={cn("rounded-md border bg-card", isDragging && "z-10 shadow-lg", errors.some((e) => e.level === "error") && "border-critical/50")} data-testid="step-row">
      <div className="flex items-center gap-2 px-2 py-2">
        {!readOnly && (
          <button {...attributes} {...listeners} className="cursor-grab rounded p-1 text-muted-foreground hover:bg-muted active:cursor-grabbing" aria-label={`Drag step ${index + 1}`}>
            <GripVertical className="h-4 w-4" />
          </button>
        )}
        <span className="tabular w-5 text-center text-xs text-muted-foreground">{index + 1}</span>
        <button className="flex min-w-0 flex-1 items-center gap-2 text-left" onClick={() => setOpen(!open)} aria-expanded={open}>
          {open ? <ChevronDown className="h-3.5 w-3.5 shrink-0" /> : <ChevronRight className="h-3.5 w-3.5 shrink-0" />}
          <span className="shrink-0 text-sm font-medium">{actionLabel(row.action)}</span>
          <span className="min-w-0 truncate font-mono text-[12px] text-muted-foreground">{stepSummary(row)}</span>
        </button>
        {!readOnly && (
          <div className="flex shrink-0 items-center">
            <Button variant="ghost" size="icon" onClick={() => move(-1)} disabled={index === 0} aria-label="Move up"><ArrowUp /></Button>
            <Button variant="ghost" size="icon" onClick={() => move(1)} disabled={index === total - 1} aria-label="Move down"><ArrowDown /></Button>
            <Button variant="ghost" size="icon" onClick={duplicate} aria-label="Duplicate step"><Copy /></Button>
            <Button variant="ghost" size="icon" onClick={remove} aria-label="Remove step"><Trash2 /></Button>
          </div>
        )}
      </div>
      {errors.length > 0 && !open && (
        <div className="px-10 pb-2">{errors.map((m, i) => <p key={i} className="flex items-center gap-1 text-xs"><MessageIcon level={m.level} />{m.message}</p>)}</div>
      )}
      {open && (
        <fieldset disabled={readOnly} className="grid gap-3 border-t bg-muted/20 px-4 py-3">
          <div className="grid gap-2 sm:grid-cols-2">
            <label className="grid gap-1 text-xs font-medium">Action
              <Select value={row.action} onChange={(e) => update({ ...blankStep(e.target.value), description: row.description, target: actions[e.target.value]?.target !== "none" ? row.target : null, value: actions[e.target.value]?.value !== "none" ? row.value : null })}>
                {GROUPS.map((g) => <optgroup key={g.label} label={g.label}>{g.actions.filter((a) => actions[a]).map((a) => <option key={a} value={a}>{actions[a].label}</option>)}</optgroup>)}
              </Select>
            </label>
            <label className="grid gap-1 text-xs font-medium">Description
              <Input value={row.description} onChange={(e) => update({ ...row, description: e.target.value })} placeholder={spec?.help} />
            </label>
          </div>
          {spec && spec.target !== "none" && (
            <div className="grid gap-1 text-xs font-medium">Element{spec.target === "optional" ? " (optional: leave blank for the whole page)" : ""}
              {spec.target === "optional" && !row.target ? (
                <Button variant="outline" size="sm" className="w-fit" onClick={() => update({ ...row, target: { strategy: "text", value: "" } })}>Choose an element</Button>
              ) : <TargetEditor step={row} onChange={update} />}
            </div>
          )}
          {row.action === "set_variable" && (
            <label className="grid gap-1 text-xs font-medium">Variable name
              <Input value={row.options?.name ?? ""} onChange={(e) => update({ ...row, options: { ...row.options, name: e.target.value } })} placeholder="customer_name" />
            </label>
          )}
          {spec && spec.value !== "none" && row.action !== "api_request" && (
            <label className="grid gap-1 text-xs font-medium">{spec.value_label}
              <Input value={row.value ?? ""} onChange={(e) => update({ ...row, value: e.target.value })}
                placeholder={row.action === "fill" ? "Text, or {{variable}} such as {{username}}" : row.action === "wait_ms" ? "1000" : ""} />
            </label>
          )}
          {row.action === "wait_for" && (
            <label className="grid gap-1 text-xs font-medium">Wait until the element is
              <Select value={row.options?.state ?? "visible"} onChange={(e) => update({ ...row, options: { ...row.options, state: e.target.value } })}><option value="visible">visible</option><option value="hidden">hidden</option></Select>
            </label>
          )}
          {row.action === "api_request" && <ApiEditor step={row} onChange={update} />}
          {errors.map((m, i) => <p key={i} className="flex items-center gap-1 text-xs"><MessageIcon level={m.level} />{m.message}</p>)}
        </fieldset>
      )}
    </li>
  );
}

export function StepEditor({ steps, onChange, messages = [], kind = "ui", readOnly }: {
  steps: Step[]; onChange: (s: Step[]) => void; messages?: ValidationMessage[]; kind?: "ui" | "api"; readOnly?: boolean;
}) {
  const { data } = useSWR<{ actions: StepAction[] }>("/step-actions", fetcher);
  const actions = React.useMemo(() => Object.fromEntries((data?.actions ?? []).map((a) => [a.action, a])), [data]);
  const [rows, setRows] = React.useState<Row[]>(() => steps.map(withKey));
  const [openKey, setOpenKey] = React.useState<string | null>(null);
  const [adding, setAdding] = React.useState(false);
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 4 } }), useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }));

  // Re-sync when the parent replaces the steps (e.g. after loading or saving).
  const external = JSON.stringify(steps);
  const lastEmitted = React.useRef(external);
  React.useEffect(() => {
    if (external !== lastEmitted.current) {
      setRows(steps.map(withKey));
      lastEmitted.current = external;
    }
  }, [external]); // eslint-disable-line react-hooks/exhaustive-deps

  const commit = (next: Row[]) => {
    setRows(next);
    const plain = next.map(strip);
    lastEmitted.current = JSON.stringify(plain);
    onChange(plain);
  };
  const onDragEnd = (e: DragEndEvent) => {
    if (!e.over || e.active.id === e.over.id) return;
    const from = rows.findIndex((r) => r._key === e.active.id);
    const to = rows.findIndex((r) => r._key === e.over!.id);
    commit(arrayMove(rows, from, to));
  };
  const add = (action: string) => {
    const r = withKey(blankStep(action));
    commit([...rows, r]);
    setOpenKey(r._key);
    setAdding(false);
  };

  return (
    <div className="grid gap-2">
      {rows.length === 0 && <p className="rounded-md border border-dashed px-4 py-6 text-center text-sm text-muted-foreground">No steps yet. Add the first step below{kind === "ui" ? ", usually Navigate to open a page" : ""}.</p>}
      <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={onDragEnd}>
        <SortableContext items={rows.map((r) => r._key)} strategy={verticalListSortingStrategy}>
          <ol className="grid gap-1.5">
            {rows.map((r, i) => (
              <StepRow key={r._key} row={r} index={i} total={rows.length} actions={actions} messages={messages} readOnly={readOnly}
                open={openKey === r._key} setOpen={(o) => setOpenKey(o ? r._key : null)}
                update={(s) => commit(rows.map((x) => (x._key === r._key ? { ...s, _key: r._key } : x)))}
                remove={() => commit(rows.filter((x) => x._key !== r._key))}
                duplicate={() => { const copy = withKey(strip(r)); const n = [...rows]; n.splice(i + 1, 0, copy); commit(n); }}
                move={(d) => commit(arrayMove(rows, i, i + d))} />
            ))}
          </ol>
        </SortableContext>
      </DndContext>
      {messages.filter((m) => m.step === null && m.level !== "info").map((m, i) => <p key={i} className="flex items-center gap-1.5 text-xs"><MessageIcon level={m.level} />{m.message}</p>)}
      {!readOnly && (
        adding ? (
          <div className="grid gap-3 rounded-md border bg-card p-3 sm:grid-cols-3" data-testid="action-palette">
            {GROUPS.map((g) => (
              <div key={g.label}>
                <p className="mb-1.5 text-xs font-medium uppercase tracking-wide text-muted-foreground">{g.label}</p>
                <div className="flex flex-wrap gap-1">
                  {g.actions.filter((a) => actions[a] && (kind === "ui" || actions[a].kind !== "ui")).map((a) => (
                    <button key={a} onClick={() => add(a)} title={actions[a].help} className="rounded-md border px-2 py-1 text-xs hover:border-primary hover:text-primary">{actions[a].label}</button>
                  ))}
                </div>
              </div>
            ))}
            <div className="sm:col-span-3"><Button variant="ghost" size="sm" onClick={() => setAdding(false)}>Cancel</Button></div>
          </div>
        ) : (
          <Button variant="outline" size="sm" className="w-fit" onClick={() => setAdding(true)} data-testid="add-step"><Plus /> Add step</Button>
        )
      )}
    </div>
  );
}

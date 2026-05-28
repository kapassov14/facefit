import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Archive, CheckSquare, ChevronDown, ChevronUp, Copy, Download, ExternalLink, Search, Tag, UserPlus } from "lucide-react";
import { useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { apiBase, apiRequest, storageUrl } from "../api/client";
import { Badge, Button, Card, Input, SectionTitle, Select, Textarea } from "../components/ui";
import { CRM_STATUSES, CrmStatusBadge, formatDate, tagColorStyle } from "./crmShared";

type Option = { id: number; name?: string; email?: string; color?: string; source?: string | null; campaign?: string | null; type?: string };
type CrmOptions = {
  statuses: { value: string; label: string }[];
  audiences: Option[];
  bases: Option[];
  tags: Option[];
  managers: Option[];
  links: Option[];
};
type CrmLead = {
  id: number;
  name?: string | null;
  phone?: string | null;
  status: string;
  selected_problems: string[];
  tag_names: string[];
  tags: { id: number | null; name: string; color?: string }[];
  source?: string | null;
  campaign?: string | null;
  bases?: { id: number; name: string; type: string }[];
  assigned_manager?: { id: number; name?: string | null; email: string } | null;
  created_at?: string;
  last_activity_at?: string;
  last_action?: string | null;
  report_opened?: boolean;
  cta_clicked?: boolean;
  has_after_photo?: boolean;
  after_photo_status?: string | null;
  tasks_count?: number;
  overdue_tasks_count?: number;
  urgency?: string;
  telegram_user?: { telegram_id: number; username?: string | null; is_blocked?: boolean; unsubscribed?: boolean } | null;
};
type KanbanSection = { status: string; label: string; total: number; items: CrmLead[] };

const emptyOptions: CrmOptions = { statuses: CRM_STATUSES, audiences: [], bases: [], tags: [], managers: [], links: [] };

function filtersToQuery(filters: Record<string, string | boolean>) {
  const params = new URLSearchParams();
  Object.entries(filters).forEach(([key, value]) => {
    if (value !== "" && value !== false && value !== undefined) params.set(key, String(value));
  });
  return params.toString();
}

async function downloadExport(filters: Record<string, string | boolean>, ids: number[]) {
  const params = new URLSearchParams(filtersToQuery(filters));
  if (ids.length) params.set("ids", ids.join(","));
  const token = localStorage.getItem("bella_admin_token");
  const response = await fetch(`${apiBase}/api/admin/crm/leads/export?${params.toString()}`, {
    headers: { Authorization: token ? `Bearer ${token}` : "", "ngrok-skip-browser-warning": "true" }
  });
  if (!response.ok) throw new Error("Не удалось экспортировать клиентов");
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = ids.length ? "crm_selected_leads.csv" : "crm_leads.csv";
  link.click();
  URL.revokeObjectURL(url);
}

function managerName(manager?: { name?: string | null; email?: string } | null) {
  return manager?.name || manager?.email || "Без ответственного";
}

export function CRM() {
  const qc = useQueryClient();
  const [searchParams] = useSearchParams();
  const [activeLeadId, setActiveLeadId] = useState<number | null>(searchParams.get("lead") ? Number(searchParams.get("lead")) : null);
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});
  const [selected, setSelected] = useState<number[]>([]);
  const [bulkStatus, setBulkStatus] = useState("");
  const [bulkManager, setBulkManager] = useState("");
  const [bulkTag, setBulkTag] = useState("");
  const [bulkBase, setBulkBase] = useState("");
  const [noteText, setNoteText] = useState("");
  const [taskTitle, setTaskTitle] = useState("");
  const [taskDue, setTaskDue] = useState("");
  const [tagText, setTagText] = useState("");
  const [filters, setFilters] = useState<Record<string, string | boolean>>({
    search: "",
    tag: "",
    base_id: searchParams.get("base_id") || "",
    manager_id: searchParams.get("manager_id") || "",
    problem: "",
    source: "",
    report_opened: "",
    cta_clicked: "",
    only_mine: false,
    unassigned: false
  });
  const query = filtersToQuery(filters);
  const { data: kanban, isLoading } = useQuery<{ sections: KanbanSection[] }>({
    queryKey: ["crm-kanban", query],
    queryFn: () => apiRequest(`/api/admin/crm/kanban?${query}`)
  });
  const { data: options = emptyOptions } = useQuery<CrmOptions>({
    queryKey: ["crm-options"],
    queryFn: () => apiRequest("/api/admin/crm/options")
  });
  const { data: detail } = useQuery<any>({
    queryKey: ["crm-lead-detail", activeLeadId],
    queryFn: () => apiRequest(`/api/admin/crm/leads/${activeLeadId}`),
    enabled: Boolean(activeLeadId)
  });
  const sections = kanban?.sections || [];
  const allLeads = useMemo(() => sections.flatMap((section) => section.items), [sections]);
  const sourceOptions = useMemo(() => Array.from(new Set(allLeads.map((item) => item.source).filter(Boolean))) as string[], [allLeads]);
  const invalidateCrm = () => {
    qc.invalidateQueries({ queryKey: ["crm-kanban"] });
    qc.invalidateQueries({ queryKey: ["crm-lead-detail"] });
    qc.invalidateQueries({ queryKey: ["admin-dashboard-stats"] });
  };
  const patchLead = useMutation({
    mutationFn: ({ id, payload }: { id: number; payload: Record<string, unknown> }) => apiRequest(`/api/admin/crm/leads/${id}`, { method: "PATCH", body: JSON.stringify(payload) }),
    onSuccess: invalidateCrm
  });
  const addNote = useMutation({
    mutationFn: () => apiRequest(`/api/admin/crm/leads/${activeLeadId}/notes`, { method: "POST", body: JSON.stringify({ text: noteText }) }),
    onSuccess: () => {
      setNoteText("");
      invalidateCrm();
    }
  });
  const addTask = useMutation({
    mutationFn: () => apiRequest(`/api/admin/crm/leads/${activeLeadId}/tasks`, { method: "POST", body: JSON.stringify({ title: taskTitle, due_at: taskDue || null, assigned_to_id: detail?.assigned_manager?.id }) }),
    onSuccess: () => {
      setTaskTitle("");
      setTaskDue("");
      invalidateCrm();
    }
  });
  const addTag = useMutation({
    mutationFn: () => apiRequest(`/api/admin/crm/leads/${activeLeadId}/tags`, { method: "POST", body: JSON.stringify({ name: tagText }) }),
    onSuccess: () => {
      setTagText("");
      invalidateCrm();
    }
  });
  const bulkAction = useMutation({
    mutationFn: (payload: Record<string, unknown>) => apiRequest("/api/admin/crm/leads/bulk-action", { method: "POST", body: JSON.stringify({ lead_ids: selected, ...payload }) }),
    onSuccess: () => {
      setSelected([]);
      invalidateCrm();
    }
  });
  const setFilter = (key: string, value: string | boolean) => setFilters((current) => ({ ...current, [key]: value }));
  const selectedCount = selected.length;
  return (
    <div>
      <SectionTitle title="CRM" subtitle="Вертикальный kanban для менеджеров: лиды, статусы, задачи, заметки и базы" />
      <Card className="mb-5">
        <div className="grid gap-3 xl:grid-cols-[minmax(260px,1.4fr)_repeat(5,minmax(150px,1fr))]">
          <div className="relative">
            <Search className="absolute left-3 top-2.5 text-clay" size={17} />
            <Input className="pl-10" value={String(filters.search)} onChange={(event) => setFilter("search", event.target.value)} placeholder="Имя, username, Telegram ID" />
          </div>
          <Select value={String(filters.base_id)} onChange={(event) => setFilter("base_id", event.target.value)}>
            <option value="">Все базы</option>
            {options.bases.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
          </Select>
          <Select value={String(filters.manager_id)} onChange={(event) => setFilter("manager_id", event.target.value)}>
            <option value="">Все менеджеры</option>
            {options.managers.map((item) => <option key={item.id} value={item.id}>{item.name || item.email}</option>)}
          </Select>
          <Select value={String(filters.tag)} onChange={(event) => setFilter("tag", event.target.value)}>
            <option value="">Все теги</option>
            {options.tags.map((item) => <option key={item.id} value={item.name}>{item.name}</option>)}
          </Select>
          <Input value={String(filters.problem)} onChange={(event) => setFilter("problem", event.target.value)} placeholder="Проблема" />
          <Select value={String(filters.source)} onChange={(event) => setFilter("source", event.target.value)}>
            <option value="">Все источники</option>
            {sourceOptions.map((item) => <option key={item} value={item}>{item}</option>)}
          </Select>
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-3 text-sm">
          <label className="inline-flex items-center gap-2"><input type="checkbox" checked={Boolean(filters.only_mine)} onChange={(event) => setFilter("only_mine", event.target.checked)} /> Только мои</label>
          <label className="inline-flex items-center gap-2"><input type="checkbox" checked={Boolean(filters.unassigned)} onChange={(event) => setFilter("unassigned", event.target.checked)} /> Без ответственного</label>
          <Select className="w-48" value={String(filters.report_opened)} onChange={(event) => setFilter("report_opened", event.target.value)}>
            <option value="">Отчет: все</option>
            <option value="true">Открывал</option>
            <option value="false">Не открывал</option>
          </Select>
          <Select className="w-44" value={String(filters.cta_clicked)} onChange={(event) => setFilter("cta_clicked", event.target.value)}>
            <option value="">CTA: все</option>
            <option value="true">Нажимал</option>
            <option value="false">Не нажимал</option>
          </Select>
          <Button type="button" variant="ghost" onClick={() => setFilters({ search: "", tag: "", base_id: "", manager_id: "", problem: "", source: "", report_opened: "", cta_clicked: "", only_mine: false, unassigned: false })}>Сбросить</Button>
        </div>
        <div className="mt-4 flex flex-wrap items-center gap-2">
          <Select className="w-48" value={bulkStatus} onChange={(event) => setBulkStatus(event.target.value)}>
            <option value="">Сменить статус</option>
            {CRM_STATUSES.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
          </Select>
          <Select className="w-52" value={bulkManager} onChange={(event) => setBulkManager(event.target.value)}>
            <option value="">Назначить менеджера</option>
            {options.managers.map((item) => <option key={item.id} value={item.id}>{item.name || item.email}</option>)}
          </Select>
          <Input className="w-44" value={bulkTag} onChange={(event) => setBulkTag(event.target.value)} placeholder="Добавить тег" />
          <Select className="w-48" value={bulkBase} onChange={(event) => setBulkBase(event.target.value)}>
            <option value="">Добавить в базу</option>
            {options.bases.filter((item) => item.type !== "dynamic").map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
          </Select>
          <Button type="button" disabled={!selectedCount || (!bulkStatus && !bulkManager && !bulkTag && !bulkBase)} onClick={() => {
            if (bulkStatus) bulkAction.mutate({ action: "set_status", status: bulkStatus });
            else if (bulkManager) bulkAction.mutate({ action: "assign_manager", manager_id: Number(bulkManager) });
            else if (bulkTag) bulkAction.mutate({ action: "add_tag", tag: bulkTag });
            else if (bulkBase) bulkAction.mutate({ action: "add_to_base", base_id: Number(bulkBase) });
          }}>
            <UserPlus size={16} />
            Применить к {selectedCount}
          </Button>
          <Button type="button" variant="secondary" onClick={() => void downloadExport(filters, selected)}>
            <Download size={16} />
            CSV
          </Button>
        </div>
      </Card>
      {isLoading ? <p className="text-sm text-clay">Загружаю kanban...</p> : null}
      <div className="space-y-4">
        {sections.map((section) => (
          <Card key={section.status} className="p-0">
            <button type="button" className="flex w-full items-center justify-between border-b border-pearl px-4 py-3 text-left" onClick={() => setCollapsed((current) => ({ ...current, [section.status]: !current[section.status] }))}>
              <div className="flex items-center gap-3">
                {collapsed[section.status] ? <ChevronDown size={18} /> : <ChevronUp size={18} />}
                <CrmStatusBadge status={section.status} />
                <span className="text-sm font-semibold text-clay">{section.total} лидов</span>
              </div>
            </button>
            {!collapsed[section.status] ? (
              <div className="grid gap-3 p-4 md:grid-cols-2 xl:grid-cols-3">
                {section.items.map((lead) => {
                  const isSelected = selected.includes(lead.id);
                  return (
                    <article key={lead.id} className={`rounded-card border p-4 transition ${lead.urgency === "high" ? "border-[#c45e5b] bg-[#fff7f6]" : "border-pearl bg-white hover:bg-milk"}`}>
                      <div className="flex items-start justify-between gap-3">
                        <label className="mt-1 inline-flex items-center gap-2">
                          <input type="checkbox" checked={isSelected} onChange={() => setSelected((current) => current.includes(lead.id) ? current.filter((id) => id !== lead.id) : [...current, lead.id])} />
                        </label>
                        <button type="button" className="flex-1 text-left" onClick={() => setActiveLeadId(lead.id)}>
                          <p className="font-bold">{lead.name || lead.telegram_user?.username || "Без имени"}</p>
                          <p className="mt-1 text-xs text-clay">@{lead.telegram_user?.username || "—"} · {formatDate(lead.last_activity_at)}</p>
                        </button>
                        {lead.overdue_tasks_count ? <Badge tone="red">срочно</Badge> : lead.cta_clicked ? <Badge tone="yellow">CTA</Badge> : null}
                      </div>
                      <div className="mt-3 flex flex-wrap gap-1">
                        {(lead.selected_problems || []).slice(0, 3).map((problem) => <Badge key={problem}>{problem}</Badge>)}
                      </div>
                      <div className="mt-3 flex flex-wrap gap-1">
                        {lead.tags?.map((tag) => <span key={`${tag.id}-${tag.name}`} className="rounded-full px-2 py-1 text-xs font-semibold" style={tagColorStyle(tag.color)}>{tag.name}</span>)}
                      </div>
                      <div className="mt-3 grid gap-2 md:grid-cols-2">
                        <Select value={lead.status} onChange={(event) => patchLead.mutate({ id: lead.id, payload: { status: event.target.value } })}>
                          {CRM_STATUSES.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
                        </Select>
                        <Select value={lead.assigned_manager?.id || ""} onChange={(event) => patchLead.mutate({ id: lead.id, payload: { assigned_manager_id: event.target.value ? Number(event.target.value) : null } })}>
                          <option value="">Без ответственного</option>
                          {options.managers.map((item) => <option key={item.id} value={item.id}>{item.name || item.email}</option>)}
                        </Select>
                      </div>
                      <div className="mt-3 flex items-center justify-between text-xs text-clay">
                        <span>{managerName(lead.assigned_manager)}</span>
                        <span>{lead.tasks_count || 0} задач · {lead.report_opened ? "отчет открыт" : "отчет нет"}</span>
                      </div>
                    </article>
                  );
                })}
                {!section.items.length ? <p className="p-3 text-sm text-clay">В этой секции нет лидов</p> : null}
              </div>
            ) : null}
          </Card>
        ))}
      </div>
      {activeLeadId ? (
        <div className="fixed inset-0 z-40 bg-ink/35" onClick={() => setActiveLeadId(null)}>
          <aside className="ml-auto h-full w-full max-w-2xl overflow-y-auto bg-white p-5 shadow-2xl" onClick={(event) => event.stopPropagation()}>
            <div className="sticky top-0 z-10 -mx-5 -mt-5 flex items-center justify-between border-b border-pearl bg-white px-5 py-4">
              <div>
                <p className="text-xs font-semibold uppercase tracking-wide text-clay">Lead Detail</p>
                <h2 className="text-xl font-bold">{detail?.name || detail?.telegram_user?.username || "Лид"}</h2>
              </div>
              <Button variant="ghost" type="button" onClick={() => setActiveLeadId(null)}>Закрыть</Button>
            </div>
            {!detail ? <p className="mt-5 text-sm text-clay">Загружаю...</p> : (
              <div className="space-y-5 pt-5">
                <Card className="shadow-none">
                  <div className="grid gap-3 md:grid-cols-2">
                    <div>
                      <p className="text-xs font-semibold text-clay">Telegram</p>
                      <p className="font-bold">@{detail.telegram_user?.username || "—"}</p>
                      <p className="text-sm text-clay">{detail.telegram_user?.telegram_id}</p>
                    </div>
                    <div>
                      <p className="text-xs font-semibold text-clay">Статус</p>
                      <Select className="mt-1" value={detail.status} onChange={(event) => patchLead.mutate({ id: detail.id, payload: { status: event.target.value } })}>
                        {CRM_STATUSES.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
                      </Select>
                    </div>
                    <div>
                      <p className="text-xs font-semibold text-clay">Менеджер</p>
                      <Select className="mt-1" value={detail.assigned_manager?.id || ""} onChange={(event) => patchLead.mutate({ id: detail.id, payload: { assigned_manager_id: event.target.value ? Number(event.target.value) : null } })}>
                        <option value="">Без ответственного</option>
                        {options.managers.map((item) => <option key={item.id} value={item.id}>{item.name || item.email}</option>)}
                      </Select>
                    </div>
                    <div>
                      <p className="text-xs font-semibold text-clay">Сигналы</p>
                      <p className="text-sm">{detail.report_opened ? "Отчет открыт" : "Отчет не открыт"} · {detail.cta_clicked ? "CTA нажат" : "CTA нет"}</p>
                    </div>
                  </div>
                  <div className="mt-4 flex flex-wrap gap-2">
                    {(detail.selected_problems || []).map((problem: string) => <Badge key={problem}>{problem}</Badge>)}
                    {(detail.tags || []).map((tag: any) => <span key={`${tag.id}-${tag.name}`} className="rounded-full px-2 py-1 text-xs font-semibold" style={tagColorStyle(tag.color)}>{tag.name}</span>)}
                  </div>
                </Card>
                <Card className="shadow-none">
                  <h3 className="mb-3 font-bold">Материалы</h3>
                  <div className="grid gap-3 md:grid-cols-2">
                    {detail.media?.original_photo_url ? <img src={storageUrl(detail.media.original_photo_url)} className="aspect-square rounded-card border border-pearl object-cover" /> : <div className="grid aspect-square place-items-center rounded-card bg-milk text-sm text-clay">Фото не загружено</div>}
                    {detail.media?.face_protocol_image_url ? <img src={storageUrl(detail.media.face_protocol_image_url)} className="aspect-square rounded-card border border-pearl object-cover" /> : <div className="grid aspect-square place-items-center rounded-card bg-milk text-sm text-clay">Протокол не готов</div>}
                  </div>
                  <div className="mt-3 flex flex-wrap gap-2">
                    {detail.report?.url ? <Link to={detail.report.url} target="_blank" className="inline-flex h-10 items-center gap-2 rounded-card bg-pearl px-3 text-sm font-semibold"><ExternalLink size={16} />Открыть отчет</Link> : null}
                    {detail.report?.url ? <Button type="button" variant="secondary" onClick={() => navigator.clipboard.writeText(`${window.location.origin}${detail.report.url}`)}><Copy size={16} />Ссылка</Button> : null}
                  </div>
                </Card>
                <Card className="shadow-none">
                  <h3 className="mb-3 font-bold">Заметки и задачи</h3>
                  <div className="grid gap-2 md:grid-cols-[1fr_auto]">
                    <Textarea className="min-h-20" value={noteText} onChange={(event) => setNoteText(event.target.value)} placeholder="Новая заметка" />
                    <Button type="button" disabled={!noteText.trim()} onClick={() => addNote.mutate()}>Добавить</Button>
                  </div>
                  <div className="mt-3 grid gap-2 md:grid-cols-[1fr_170px_auto]">
                    <Input value={taskTitle} onChange={(event) => setTaskTitle(event.target.value)} placeholder="Задача" />
                    <Input type="datetime-local" value={taskDue} onChange={(event) => setTaskDue(event.target.value)} />
                    <Button type="button" disabled={!taskTitle.trim()} onClick={() => addTask.mutate()}><CheckSquare size={16} />Задача</Button>
                  </div>
                  <div className="mt-3 grid gap-2 md:grid-cols-[1fr_auto]">
                    <Input value={tagText} onChange={(event) => setTagText(event.target.value)} placeholder="Новый тег" />
                    <Button type="button" disabled={!tagText.trim()} onClick={() => addTag.mutate()}><Tag size={16} />Тег</Button>
                  </div>
                </Card>
                <Card className="shadow-none">
                  <h3 className="mb-3 font-bold">Timeline</h3>
                  <div className="space-y-3">
                    {[...(detail.activities || []), ...(detail.events || [])].slice(0, 30).map((event: any, index: number) => (
                      <div key={`${event.id}-${event.event_type || event.type}-${index}`} className="rounded-card border border-pearl p-3 text-sm">
                        <p className="font-semibold">{event.payload?.title || event.title || event.event_type || event.type}</p>
                        <p className="text-xs text-clay">{formatDate(event.created_at)} · {event.actor?.email || event.created_by?.email || event.actor_type || "system"}</p>
                      </div>
                    ))}
                  </div>
                </Card>
                <Card className="shadow-none">
                  <h3 className="mb-3 font-bold">Задачи</h3>
                  <div className="space-y-2">
                    {(detail.tasks || []).map((task: any) => (
                      <div key={task.id} className="flex items-center justify-between rounded-card bg-milk p-3 text-sm">
                        <div>
                          <p className="font-semibold">{task.title}</p>
                          <p className="text-xs text-clay">{task.status} · {formatDate(task.due_at)} · {managerName(task.assigned_to)}</p>
                        </div>
                        {task.status === "todo" ? <Button type="button" variant="secondary" onClick={() => apiRequest(`/api/admin/crm/leads/${detail.id}/tasks/${task.id}`, { method: "PATCH", body: JSON.stringify({ status: "done" }) }).then(invalidateCrm)}>Готово</Button> : null}
                      </div>
                    ))}
                  </div>
                </Card>
                <div className="sticky bottom-0 -mx-5 flex flex-wrap gap-2 border-t border-pearl bg-white p-4">
                  <Button type="button" onClick={() => patchLead.mutate({ id: detail.id, payload: { status: "paid" } })}>Оплатил</Button>
                  <Button type="button" variant="secondary" onClick={() => patchLead.mutate({ id: detail.id, payload: { status: "manual_contact" } })}>Написать вручную</Button>
                  <Button type="button" variant="ghost" onClick={() => patchLead.mutate({ id: detail.id, payload: { status: "archived" } })}><Archive size={16} />Архив</Button>
                </div>
              </div>
            )}
          </aside>
        </div>
      ) : null}
    </div>
  );
}

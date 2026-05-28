import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Archive, Download, FileText, Plus, Search, SlidersHorizontal, UserPlus } from "lucide-react";
import { useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { apiBase, apiRequest } from "../api/client";
import { Badge, Button, Card, Input, SectionTitle, Select } from "../components/ui";
import { CRM_STATUSES, CrmStatusBadge, formatDate, tagColorStyle } from "./crmShared";

type Option = { id: number; name?: string; email?: string; color?: string; source?: string | null; campaign?: string | null };
type CrmOptions = {
  statuses: { value: string; label: string }[];
  audiences: Option[];
  tags: Option[];
  managers: Option[];
  links: Option[];
};
type CrmLead = {
  id: number;
  name?: string | null;
  phone?: string | null;
  status: string;
  tag_names: string[];
  tags: { id: number | null; name: string; color?: string }[];
  source?: string | null;
  campaign?: string | null;
  audience?: { id: number; name: string; color?: string } | null;
  assigned_manager?: { id: number; email: string } | null;
  first_source_link?: { id: number; name: string } | null;
  last_source_link?: { id: number; name: string } | null;
  created_at?: string;
  last_activity_at?: string;
  last_action?: string | null;
  touch_count: number;
  telegram_user?: { telegram_id: number; username?: string | null; first_name?: string | null; last_name?: string | null } | null;
};
type CrmStats = {
  total: number;
  new_today: number;
  new_7_days: number;
  applications: number;
  purchases: number;
  application_conversion: number;
  purchase_conversion: number;
  best_source?: { source: string; count: number } | null;
};

const emptyOptions: CrmOptions = { statuses: CRM_STATUSES, audiences: [], tags: [], managers: [], links: [] };

function filtersToQuery(filters: Record<string, string>) {
  const params = new URLSearchParams();
  Object.entries(filters).forEach(([key, value]) => {
    if (value) params.set(key, value);
  });
  return params.toString();
}

async function downloadExport(filters: Record<string, string>, ids: number[]) {
  const params = new URLSearchParams(filtersToQuery(filters));
  if (ids.length) params.set("ids", ids.join(","));
  const token = localStorage.getItem("bella_admin_token");
  const response = await fetch(`${apiBase}/api/admin/crm/leads/export?${params.toString()}`, {
    headers: {
      Authorization: token ? `Bearer ${token}` : "",
      "ngrok-skip-browser-warning": "true"
    }
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

export function CRM() {
  const qc = useQueryClient();
  const [searchParams] = useSearchParams();
  const [selected, setSelected] = useState<number[]>([]);
  const [bulkStatus, setBulkStatus] = useState("");
  const [bulkManager, setBulkManager] = useState("");
  const [bulkTag, setBulkTag] = useState("");
  const [filters, setFilters] = useState<Record<string, string>>({
    search: "",
    status: "",
    tag: "",
    source: "",
    source_link_id: "",
    audience_id: searchParams.get("audience_id") || "",
    manager_id: searchParams.get("manager_id") || "",
    date_from: "",
    date_to: "",
    activity_from: "",
    activity_to: ""
  });
  const query = filtersToQuery(filters);
  const { data } = useQuery<{ items: CrmLead[]; total: number }>({
    queryKey: ["crm-leads", query],
    queryFn: () => apiRequest(`/api/admin/crm/leads?${query}`)
  });
  const { data: stats } = useQuery<CrmStats>({ queryKey: ["crm-stats"], queryFn: () => apiRequest("/api/admin/crm/stats") });
  const { data: options = emptyOptions } = useQuery<CrmOptions>({
    queryKey: ["crm-options"],
    queryFn: () => apiRequest("/api/admin/crm/options")
  });
  const leads = data?.items || [];
  const sourceOptions = useMemo(() => {
    const values = new Set<string>();
    options.links.forEach((item) => {
      if (item.source) values.add(item.source);
    });
    leads.forEach((item) => {
      if (item.source) values.add(item.source);
    });
    return Array.from(values);
  }, [leads, options.links]);
  const updateLead = useMutation({
    mutationFn: ({ id, payload }: { id: number; payload: Record<string, unknown> }) =>
      apiRequest(`/api/admin/crm/leads/${id}`, { method: "PATCH", body: JSON.stringify(payload) }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["crm-leads"] });
      qc.invalidateQueries({ queryKey: ["crm-stats"] });
    }
  });
  const bulkApply = async () => {
    const selectedLeads = leads.filter((lead) => selected.includes(lead.id));
    await Promise.all(
      selectedLeads.map((lead) => {
        const payload: Record<string, unknown> = {};
        if (bulkStatus) payload.status = bulkStatus;
        if (bulkManager) payload.assigned_manager_id = Number(bulkManager);
        if (bulkTag) payload.tags = Array.from(new Set([...lead.tag_names, bulkTag.trim()].filter(Boolean)));
        return apiRequest(`/api/admin/crm/leads/${lead.id}`, { method: "PATCH", body: JSON.stringify(payload) });
      })
    );
    setBulkTag("");
    qc.invalidateQueries({ queryKey: ["crm-leads"] });
    qc.invalidateQueries({ queryKey: ["crm-stats"] });
  };
  const setFilter = (key: string, value: string) => setFilters((current) => ({ ...current, [key]: value }));
  const statCards = [
    ["Всего клиентов", stats?.total ?? 0],
    ["Новые сегодня", stats?.new_today ?? 0],
    ["Новые за 7 дней", stats?.new_7_days ?? 0],
    ["Оставили заявку", stats?.applications ?? 0],
    ["Купили", stats?.purchases ?? 0],
    ["Конверсия в заявку", `${stats?.application_conversion ?? 0}%`],
    ["Конверсия в покупку", `${stats?.purchase_conversion ?? 0}%`],
    ["Эффективный источник", stats?.best_source ? `${stats.best_source.source} · ${stats.best_source.count}` : "—"]
  ];
  return (
    <div>
      <SectionTitle title="CRM" subtitle="Клиенты, источники, статусы, касания и менеджеры" />
      <div className="mb-5 grid gap-3 md:grid-cols-4 xl:grid-cols-8">
        {statCards.map(([label, value]) => (
          <Card key={label} className="p-4">
            <p className="text-xs font-semibold text-clay">{label}</p>
            <p className="mt-2 text-xl font-bold text-ink">{value}</p>
          </Card>
        ))}
      </div>
      <Card className="mb-5">
        <div className="mb-4 flex items-center gap-2 text-sm font-bold text-ink">
          <SlidersHorizontal size={17} />
          Фильтры и быстрые действия
        </div>
        <div className="grid gap-3 lg:grid-cols-[minmax(240px,1.4fr)_repeat(4,minmax(150px,1fr))]">
          <div className="relative">
            <Search className="absolute left-3 top-2.5 text-clay" size={17} />
            <Input className="pl-10" value={filters.search} onChange={(event) => setFilter("search", event.target.value)} placeholder="Имя, username, телефон, Telegram ID" />
          </div>
          <Select value={filters.status} onChange={(event) => setFilter("status", event.target.value)}>
            <option value="">Все статусы</option>
            {CRM_STATUSES.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
          </Select>
          <Select value={filters.audience_id} onChange={(event) => setFilter("audience_id", event.target.value)}>
            <option value="">Все базы</option>
            {options.audiences.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
          </Select>
          <Select value={filters.source_link_id} onChange={(event) => setFilter("source_link_id", event.target.value)}>
            <option value="">Все ссылки</option>
            {options.links.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
          </Select>
          <Select value={filters.manager_id} onChange={(event) => setFilter("manager_id", event.target.value)}>
            <option value="">Все менеджеры</option>
            {options.managers.map((item) => <option key={item.id} value={item.id}>{item.email}</option>)}
          </Select>
        </div>
        <div className="mt-3 grid gap-3 md:grid-cols-6">
          <Select value={filters.source} onChange={(event) => setFilter("source", event.target.value)}>
            <option value="">Все источники</option>
            {sourceOptions.map((item) => <option key={item} value={item}>{item}</option>)}
          </Select>
          <Select value={filters.tag} onChange={(event) => setFilter("tag", event.target.value)}>
            <option value="">Все теги</option>
            {options.tags.map((item) => <option key={item.id} value={item.name}>{item.name}</option>)}
          </Select>
          <Input type="date" value={filters.date_from} onChange={(event) => setFilter("date_from", event.target.value)} />
          <Input type="date" value={filters.date_to} onChange={(event) => setFilter("date_to", event.target.value)} />
          <Input type="date" value={filters.activity_from} onChange={(event) => setFilter("activity_from", event.target.value)} />
          <Input type="date" value={filters.activity_to} onChange={(event) => setFilter("activity_to", event.target.value)} />
        </div>
        <div className="mt-4 flex flex-wrap items-center gap-2">
          <Select className="w-44" value={bulkStatus} onChange={(event) => setBulkStatus(event.target.value)}>
            <option value="">Статус</option>
            {CRM_STATUSES.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
          </Select>
          <Select className="w-52" value={bulkManager} onChange={(event) => setBulkManager(event.target.value)}>
            <option value="">Менеджер</option>
            {options.managers.map((item) => <option key={item.id} value={item.id}>{item.email}</option>)}
          </Select>
          <Input className="w-44" value={bulkTag} onChange={(event) => setBulkTag(event.target.value)} placeholder="Добавить тег" />
          <Button type="button" onClick={bulkApply} disabled={!selected.length || (!bulkStatus && !bulkManager && !bulkTag)}>
            <UserPlus size={16} />
            Применить к {selected.length || 0}
          </Button>
          <Button type="button" variant="secondary" onClick={() => void downloadExport(filters, selected)}>
            <Download size={16} />
            CSV
          </Button>
          <Button type="button" variant="ghost" onClick={() => setFilters({ search: "", status: "", tag: "", source: "", source_link_id: "", audience_id: "", manager_id: "", date_from: "", date_to: "", activity_from: "", activity_to: "" })}>
            Сбросить
          </Button>
        </div>
      </Card>
      <Card className="overflow-hidden p-0">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[1320px] text-sm">
            <thead className="bg-pearl/60 text-left text-clay">
              <tr>
                <th className="w-10 p-3"></th>
                <th className="p-3">Клиент</th>
                <th className="p-3">Telegram</th>
                <th className="p-3">Статус</th>
                <th className="p-3">Теги</th>
                <th className="p-3">Источник</th>
                <th className="p-3">Ссылка</th>
                <th className="p-3">База</th>
                <th className="p-3">Первый вход</th>
                <th className="p-3">Активность</th>
                <th className="p-3">Менеджер</th>
                <th className="p-3">Последнее действие</th>
                <th className="p-3">Касания</th>
                <th className="p-3"></th>
              </tr>
            </thead>
            <tbody>
              {leads.map((lead) => {
                const isSelected = selected.includes(lead.id);
                return (
                  <tr key={lead.id} className="border-t border-pearl align-top hover:bg-milk/70">
                    <td className="p-3">
                      <input
                        type="checkbox"
                        checked={isSelected}
                        onChange={() => setSelected((current) => (current.includes(lead.id) ? current.filter((id) => id !== lead.id) : [...current, lead.id]))}
                      />
                    </td>
                    <td className="p-3">
                      <Link to={`/admin/crm/${lead.id}`} className="font-bold text-ink hover:text-rose">{lead.name || "Без имени"}</Link>
                      <p className="mt-1 text-xs text-clay">{lead.phone || "Телефон не указан"}</p>
                    </td>
                    <td className="p-3">
                      <p>@{lead.telegram_user?.username || "—"}</p>
                      <p className="text-xs text-clay">{lead.telegram_user?.telegram_id || "—"}</p>
                    </td>
                    <td className="p-3">
                      <Select value={lead.status} onChange={(event) => updateLead.mutate({ id: lead.id, payload: { status: event.target.value } })}>
                        {CRM_STATUSES.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
                      </Select>
                    </td>
                    <td className="p-3">
                      <div className="flex max-w-[210px] flex-wrap gap-1">
                        {lead.tags.length ? lead.tags.map((tag) => <span key={`${tag.id}-${tag.name}`} className="rounded-full px-2 py-1 text-xs font-semibold" style={tagColorStyle(tag.color)}>{tag.name}</span>) : <span className="text-clay">—</span>}
                      </div>
                    </td>
                    <td className="p-3">
                      <Badge>{lead.source || "—"}</Badge>
                      {lead.campaign ? <p className="mt-1 text-xs text-clay">{lead.campaign}</p> : null}
                    </td>
                    <td className="p-3">{lead.last_source_link?.name || lead.first_source_link?.name || "—"}</td>
                    <td className="p-3">{lead.audience ? <span className="font-semibold" style={{ color: lead.audience.color }}>{lead.audience.name}</span> : "—"}</td>
                    <td className="p-3">{formatDate(lead.created_at)}</td>
                    <td className="p-3">{formatDate(lead.last_activity_at)}</td>
                    <td className="p-3">
                      <Select value={lead.assigned_manager?.id || ""} onChange={(event) => updateLead.mutate({ id: lead.id, payload: { assigned_manager_id: event.target.value ? Number(event.target.value) : null } })}>
                        <option value="">Не назначен</option>
                        {options.managers.map((item) => <option key={item.id} value={item.id}>{item.email}</option>)}
                      </Select>
                    </td>
                    <td className="max-w-[220px] p-3 text-clay">{lead.last_action || "—"}</td>
                    <td className="p-3 font-bold">{lead.touch_count}</td>
                    <td className="p-3">
                      <div className="flex gap-2">
                        <Link to={`/admin/crm/${lead.id}`} className="inline-flex h-9 items-center justify-center rounded-card bg-pearl px-3 text-sm font-semibold text-ink hover:bg-[#ead9cf]">
                          <FileText size={15} />
                        </Link>
                        <Button className="h-9 px-3" variant="ghost" type="button" onClick={() => updateLead.mutate({ id: lead.id, payload: { status: "archived" } })}>
                          <Archive size={15} />
                        </Button>
                      </div>
                    </td>
                  </tr>
                );
              })}
              {!leads.length ? (
                <tr>
                  <td className="p-8 text-center text-clay" colSpan={14}>
                    Клиенты не найдены
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </Card>
      <div className="mt-4 flex justify-between text-sm text-clay">
        <span>Найдено: {data?.total ?? 0}</span>
        <Link to="/admin/links" className="inline-flex items-center gap-2 font-semibold text-rose">
          <Plus size={15} />
          Создать ссылку привлечения
        </Link>
      </div>
    </div>
  );
}

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, MessageSquarePlus, Plus, Save, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { apiRequest } from "../api/client";
import { Badge, Button, Card, Input, SectionTitle, Select, Textarea } from "../components/ui";
import { CRM_STATUSES, CrmStatusBadge, formatDate, tagColorStyle } from "./crmShared";

type CrmOptions = {
  audiences: { id: number; name: string; color?: string }[];
  managers: { id: number; email: string }[];
  tags: { id: number; name: string; color?: string }[];
};
type DetailLead = {
  id: number;
  name?: string | null;
  phone?: string | null;
  status: string;
  technical_status?: string;
  source?: string | null;
  campaign?: string | null;
  tags: { id: number | null; name: string; color?: string }[];
  tag_names: string[];
  audience?: { id: number; name: string; color?: string } | null;
  assigned_manager?: { id: number; email: string } | null;
  first_source_link?: { id: number; name: string; source?: string | null; campaign?: string | null } | null;
  last_source_link?: { id: number; name: string; source?: string | null; campaign?: string | null } | null;
  created_at?: string;
  last_activity_at?: string;
  telegram_user?: { telegram_id: number; username?: string | null; first_name?: string | null; last_name?: string | null } | null;
  events: { id: number; type: string; title: string; created_at?: string; created_by?: { email: string } | null; metadata?: Record<string, unknown> }[];
  touchpoints: { id: number; source?: string | null; campaign?: string | null; created_at?: string; source_link?: { name: string } | null }[];
  notes: { id: number; text: string; created_at?: string; author?: { email: string } | null }[];
  analyses: { id: number; status: string; created_at?: string; selected_problems: string[] }[];
};

export function CrmLeadDetail() {
  const { id } = useParams();
  const qc = useQueryClient();
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [note, setNote] = useState("");
  const [newTag, setNewTag] = useState("");
  const { data } = useQuery<DetailLead>({ queryKey: ["crm-lead", id], queryFn: () => apiRequest(`/api/admin/crm/leads/${id}`), enabled: Boolean(id) });
  const { data: options } = useQuery<CrmOptions>({ queryKey: ["crm-options"], queryFn: () => apiRequest("/api/admin/crm/options") });
  useEffect(() => {
    if (!data) return;
    setName(data.name || "");
    setPhone(data.phone || "");
  }, [data]);
  const patchLead = useMutation({
    mutationFn: (payload: Record<string, unknown>) => apiRequest(`/api/admin/crm/leads/${id}`, { method: "PATCH", body: JSON.stringify(payload) }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["crm-lead", id] });
      qc.invalidateQueries({ queryKey: ["crm-leads"] });
    }
  });
  const addNote = useMutation({
    mutationFn: () => apiRequest(`/api/admin/crm/leads/${id}/notes`, { method: "POST", body: JSON.stringify({ text: note }) }),
    onSuccess: () => {
      setNote("");
      qc.invalidateQueries({ queryKey: ["crm-lead", id] });
    }
  });
  const addTag = useMutation({
    mutationFn: () => apiRequest(`/api/admin/crm/leads/${id}/tags`, { method: "POST", body: JSON.stringify({ name: newTag }) }),
    onSuccess: () => {
      setNewTag("");
      qc.invalidateQueries({ queryKey: ["crm-lead", id] });
      qc.invalidateQueries({ queryKey: ["crm-options"] });
    }
  });
  const removeTag = useMutation({
    mutationFn: (tagId: number) => apiRequest(`/api/admin/crm/leads/${id}/tags/${tagId}`, { method: "DELETE" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["crm-lead", id] });
    }
  });
  if (!data) return <p>Загружаю...</p>;
  const baseInfo = [
    ["Telegram username", data.telegram_user?.username ? `@${data.telegram_user.username}` : "—"],
    ["Telegram ID", data.telegram_user?.telegram_id || "—"],
    ["Источник первого входа", data.first_source_link?.source || data.source || "—"],
    ["Последняя ссылка", data.last_source_link?.name || "—"],
    ["Кампания", data.campaign || data.last_source_link?.campaign || "—"],
    ["База", data.audience?.name || "—"],
    ["Первый вход", formatDate(data.created_at)],
    ["Последняя активность", formatDate(data.last_activity_at)]
  ];
  return (
    <div>
      <Link to="/admin/crm" className="mb-4 inline-flex items-center gap-2 text-sm font-semibold text-clay hover:text-rose">
        <ArrowLeft size={16} />
        CRM
      </Link>
      <SectionTitle title={data.name || "Клиент"} subtitle={`Telegram ID: ${data.telegram_user?.telegram_id || "—"}`} />
      <div className="grid gap-5 xl:grid-cols-[1fr_380px]">
        <div className="space-y-5">
          <Card>
            <div className="mb-5 flex flex-wrap items-center gap-3">
              <CrmStatusBadge status={data.status} />
              <Badge>{data.technical_status || "bot"}</Badge>
              {data.assigned_manager ? <Badge>{data.assigned_manager.email}</Badge> : null}
            </div>
            <div className="grid gap-3 md:grid-cols-2">
              <div>
                <label className="text-xs font-semibold text-clay">Имя</label>
                <Input className="mt-1" value={name} onChange={(event) => setName(event.target.value)} />
              </div>
              <div>
                <label className="text-xs font-semibold text-clay">Телефон</label>
                <Input className="mt-1" value={phone} onChange={(event) => setPhone(event.target.value)} placeholder="+7..." />
              </div>
              <div>
                <label className="text-xs font-semibold text-clay">Статус</label>
                <Select className="mt-1" value={data.status} onChange={(event) => patchLead.mutate({ status: event.target.value })}>
                  {CRM_STATUSES.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
                </Select>
              </div>
              <div>
                <label className="text-xs font-semibold text-clay">Менеджер</label>
                <Select className="mt-1" value={data.assigned_manager?.id || ""} onChange={(event) => patchLead.mutate({ assigned_manager_id: event.target.value ? Number(event.target.value) : null })}>
                  <option value="">Не назначен</option>
                  {(options?.managers || []).map((item) => <option key={item.id} value={item.id}>{item.email}</option>)}
                </Select>
              </div>
              <div>
                <label className="text-xs font-semibold text-clay">База</label>
                <Select className="mt-1" value={data.audience?.id || ""} onChange={(event) => patchLead.mutate({ audience_id: event.target.value ? Number(event.target.value) : null })}>
                  <option value="">Без базы</option>
                  {(options?.audiences || []).map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
                </Select>
              </div>
              <div className="flex items-end">
                <Button type="button" onClick={() => patchLead.mutate({ name, phone })}>
                  <Save size={16} />
                  Сохранить данные
                </Button>
              </div>
            </div>
            <div className="mt-5 grid gap-3 md:grid-cols-2">
              {baseInfo.map(([label, value]) => (
                <div key={label} className="rounded-card border border-pearl bg-milk/50 p-3">
                  <p className="text-xs font-semibold text-clay">{label}</p>
                  <p className="mt-1 font-semibold text-ink">{value}</p>
                </div>
              ))}
            </div>
          </Card>
          <Card>
            <h2 className="font-bold">История клиента</h2>
            <div className="mt-4 space-y-3">
              {[...data.events, ...data.touchpoints.map((item) => ({ id: -item.id, type: "touchpoint", title: `Переход по ссылке ${item.source_link?.name || item.source || "—"}`, created_at: item.created_at, created_by: null }))]
                .sort((a, b) => new Date(b.created_at || 0).getTime() - new Date(a.created_at || 0).getTime())
                .map((event) => (
                  <div key={`${event.type}-${event.id}`} className="border-l-2 border-rose/45 py-1 pl-4">
                    <p className="font-semibold">{event.title}</p>
                    <p className="mt-1 text-xs text-clay">{formatDate(event.created_at)} {event.created_by ? `· ${event.created_by.email}` : ""}</p>
                  </div>
                ))}
              {!data.events.length && !data.touchpoints.length ? <p className="text-sm text-clay">История пока пустая</p> : null}
            </div>
          </Card>
          <Card>
            <h2 className="font-bold">Анализы и сценарии</h2>
            <div className="mt-3 grid gap-3 md:grid-cols-2">
              {data.analyses.map((analysis) => (
                <Link key={analysis.id} to={`/admin/analysis/${analysis.id}`} className="rounded-card border border-pearl p-3 hover:bg-milk">
                  <p className="font-semibold">Анализ #{analysis.id}</p>
                  <p className="mt-1 text-xs text-clay">{analysis.status} · {formatDate(analysis.created_at)}</p>
                  <p className="mt-2 text-sm">{analysis.selected_problems.join(", ") || "Без выбранных зон"}</p>
                </Link>
              ))}
              {!data.analyses.length ? <p className="text-sm text-clay">Анализов пока нет</p> : null}
            </div>
          </Card>
        </div>
        <div className="space-y-5">
          <Card>
            <h2 className="font-bold">Сегменты и теги</h2>
            <div className="mt-4 flex flex-wrap gap-2">
              {data.tags.map((tag) => (
                <span key={`${tag.id}-${tag.name}`} className="inline-flex items-center gap-2 rounded-full px-3 py-1 text-xs font-semibold" style={tagColorStyle(tag.color)}>
                  {tag.name}
                  {tag.id ? (
                    <button type="button" onClick={() => removeTag.mutate(tag.id!)} className="text-clay hover:text-ink">
                      <Trash2 size={12} />
                    </button>
                  ) : null}
                </span>
              ))}
              {!data.tags.length ? <span className="text-sm text-clay">Тегов нет</span> : null}
            </div>
            <div className="mt-4 grid grid-cols-[1fr_auto] gap-2">
              <Input value={newTag} onChange={(event) => setNewTag(event.target.value)} placeholder="Новый тег" />
              <Button type="button" onClick={() => addTag.mutate()} disabled={!newTag.trim()}>
                <Plus size={16} />
              </Button>
            </div>
          </Card>
          <Card>
            <h2 className="font-bold">Заметки менеджера</h2>
            <Textarea className="mt-4" value={note} onChange={(event) => setNote(event.target.value)} placeholder="Новая заметка" />
            <Button className="mt-3 w-full" type="button" onClick={() => addNote.mutate()} disabled={!note.trim()}>
              <MessageSquarePlus size={16} />
              Добавить заметку
            </Button>
            <div className="mt-5 space-y-3">
              {data.notes.map((item) => (
                <div key={item.id} className="rounded-card border border-pearl p-3">
                  <p className="text-sm">{item.text}</p>
                  <p className="mt-2 text-xs text-clay">{formatDate(item.created_at)} · {item.author?.email || "Админ"}</p>
                </div>
              ))}
              {!data.notes.length ? <p className="text-sm text-clay">Заметок пока нет</p> : null}
            </div>
          </Card>
        </div>
      </div>
    </div>
  );
}

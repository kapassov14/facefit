import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Copy, ExternalLink, Link as LinkIcon, QrCode, ToggleLeft, ToggleRight, Trash2 } from "lucide-react";
import { useMemo, useState } from "react";

import { apiRequest } from "../api/client";
import { Badge, Button, Card, Input, SectionTitle, Select, Textarea } from "../components/ui";
import { formatDate, tagColorStyle } from "./crmShared";

type Options = {
  audiences: { id: number; name: string; color?: string }[];
  managers: { id: number; email: string }[];
  tags: { id: number; name: string; color?: string }[];
};
type SourceLink = {
  id: number;
  name: string;
  slug: string;
  full_url: string;
  source?: string | null;
  source_label?: string;
  campaign?: string | null;
  description?: string | null;
  audience?: { id: number; name: string; color?: string } | null;
  tags: string[];
  funnel_id?: number | null;
  assigned_manager?: { id: number; email: string } | null;
  is_active: boolean;
  created_at?: string;
  metrics: {
    clicks: number;
    unique_users: number;
    new_users: number;
    applications: number;
    purchases: number;
    click_to_application: number;
    application_to_purchase: number;
    last_touch_at?: string | null;
  };
};
type LinksResponse = {
  items: SourceLink[];
  sources: { value: string; label: string }[];
};

const initialForm = {
  name: "",
  slug: "",
  source: "instagram",
  campaign: "",
  description: "",
  audience_id: "",
  tags: "",
  funnel_id: "",
  assigned_manager_id: "",
  is_active: true
};

export function Links() {
  const qc = useQueryClient();
  const [form, setForm] = useState(initialForm);
  const [qrUrl, setQrUrl] = useState("");
  const { data } = useQuery<LinksResponse>({ queryKey: ["source-links"], queryFn: () => apiRequest("/api/admin/links") });
  const { data: options } = useQuery<Options>({ queryKey: ["crm-options"], queryFn: () => apiRequest("/api/admin/crm/options") });
  const links = data?.items || [];
  const sourceOptions = data?.sources || [];
  const totals = useMemo(() => {
    return links.reduce(
      (acc, link) => {
        acc.clicks += link.metrics.clicks;
        acc.newUsers += link.metrics.new_users;
        acc.applications += link.metrics.applications;
        acc.purchases += link.metrics.purchases;
        return acc;
      },
      { clicks: 0, newUsers: 0, applications: 0, purchases: 0 }
    );
  }, [links]);
  const create = useMutation({
    mutationFn: () =>
      apiRequest("/api/admin/links", {
        method: "POST",
        body: JSON.stringify({
          name: form.name,
          slug: form.slug,
          source: form.source,
          campaign: form.campaign || null,
          description: form.description || null,
          audience_id: form.audience_id ? Number(form.audience_id) : null,
          tags: form.tags.split(",").map((item) => item.trim()).filter(Boolean),
          funnel_id: form.funnel_id ? Number(form.funnel_id) : null,
          assigned_manager_id: form.assigned_manager_id ? Number(form.assigned_manager_id) : null,
          is_active: form.is_active
        })
      }),
    onSuccess: () => {
      setForm(initialForm);
      qc.invalidateQueries({ queryKey: ["source-links"] });
      qc.invalidateQueries({ queryKey: ["crm-options"] });
    }
  });
  const patch = useMutation({
    mutationFn: ({ id, payload }: { id: number; payload: Record<string, unknown> }) =>
      apiRequest(`/api/admin/links/${id}`, { method: "PATCH", body: JSON.stringify(payload) }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["source-links"] });
      qc.invalidateQueries({ queryKey: ["crm-options"] });
    }
  });
  const remove = useMutation({
    mutationFn: (id: number) => apiRequest(`/api/admin/links/${id}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["source-links"] })
  });
  const setField = (key: keyof typeof initialForm, value: string | boolean) => setForm((current) => ({ ...current, [key]: value }));
  const copy = async (url: string) => {
    await navigator.clipboard.writeText(url);
  };
  return (
    <div>
      <SectionTitle title="Ссылки / Источники / UTM" subtitle="Конструктор Telegram deep links и аналитика привлечения" />
      <div className="mb-5 grid gap-3 md:grid-cols-4">
        <Card className="p-4"><p className="text-xs font-semibold text-clay">Переходы</p><p className="mt-2 text-2xl font-bold">{totals.clicks}</p></Card>
        <Card className="p-4"><p className="text-xs font-semibold text-clay">Новые пользователи</p><p className="mt-2 text-2xl font-bold">{totals.newUsers}</p></Card>
        <Card className="p-4"><p className="text-xs font-semibold text-clay">Заявки</p><p className="mt-2 text-2xl font-bold">{totals.applications}</p></Card>
        <Card className="p-4"><p className="text-xs font-semibold text-clay">Покупки</p><p className="mt-2 text-2xl font-bold">{totals.purchases}</p></Card>
      </div>
      <Card className="mb-5">
        <div className="mb-4 flex items-center gap-2 font-bold">
          <LinkIcon size={18} />
          Новая ссылка
        </div>
        <div className="grid gap-3 lg:grid-cols-4">
          <Input placeholder="Название ссылки" value={form.name} onChange={(event) => setField("name", event.target.value)} />
          <Input placeholder="slug / код" value={form.slug} onChange={(event) => setField("slug", event.target.value)} />
          <Select value={form.source} onChange={(event) => setField("source", event.target.value)}>
            {sourceOptions.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
          </Select>
          <Input placeholder="Кампания" value={form.campaign} onChange={(event) => setField("campaign", event.target.value)} />
          <Select value={form.audience_id} onChange={(event) => setField("audience_id", event.target.value)}>
            <option value="">База</option>
            {(options?.audiences || []).map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
          </Select>
          <Input placeholder="Авто-теги через запятую" value={form.tags} onChange={(event) => setField("tags", event.target.value)} />
          <Input placeholder="ID стартового сценария" value={form.funnel_id} onChange={(event) => setField("funnel_id", event.target.value)} />
          <Select value={form.assigned_manager_id} onChange={(event) => setField("assigned_manager_id", event.target.value)}>
            <option value="">Ответственный</option>
            {(options?.managers || []).map((item) => <option key={item.id} value={item.id}>{item.email}</option>)}
          </Select>
        </div>
        <div className="mt-3 grid gap-3 md:grid-cols-[1fr_auto_auto]">
          <Textarea className="min-h-20" placeholder="Описание" value={form.description} onChange={(event) => setField("description", event.target.value)} />
          <label className="flex h-10 items-center gap-2 self-start rounded-card border border-pearl bg-white px-3 text-sm font-semibold">
            <input type="checkbox" checked={form.is_active} onChange={(event) => setField("is_active", event.target.checked)} />
            Активна
          </label>
          <Button type="button" onClick={() => create.mutate()} disabled={!form.name || !form.slug}>
            Создать
          </Button>
        </div>
      </Card>
      <Card className="overflow-hidden p-0">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[1240px] text-sm">
            <thead className="bg-pearl/60 text-left text-clay">
              <tr>
                <th className="p-3">Название</th>
                <th className="p-3">Ссылка</th>
                <th className="p-3">Источник</th>
                <th className="p-3">Кампания</th>
                <th className="p-3">База</th>
                <th className="p-3">Теги</th>
                <th className="p-3">Сценарий</th>
                <th className="p-3">Переходы</th>
                <th className="p-3">Новые</th>
                <th className="p-3">Заявки</th>
                <th className="p-3">Покупки</th>
                <th className="p-3">Конверсия</th>
                <th className="p-3">Создана</th>
                <th className="p-3">Статус</th>
                <th className="p-3"></th>
              </tr>
            </thead>
            <tbody>
              {links.map((link) => (
                <tr key={link.id} className="border-t border-pearl align-top hover:bg-milk/70">
                  <td className="p-3 font-bold">{link.name}</td>
                  <td className="max-w-[260px] p-3 text-rose">
                    <p className="truncate">{link.full_url}</p>
                    <p className="mt-1 text-xs text-clay">Последний переход: {formatDate(link.metrics.last_touch_at)}</p>
                  </td>
                  <td className="p-3"><Badge>{link.source_label || link.source || "—"}</Badge></td>
                  <td className="p-3">{link.campaign || "—"}</td>
                  <td className="p-3">{link.audience ? <span style={{ color: link.audience.color }} className="font-semibold">{link.audience.name}</span> : "—"}</td>
                  <td className="p-3">
                    <div className="flex max-w-[180px] flex-wrap gap-1">
                      {link.tags.length ? link.tags.map((tag) => <span key={tag} className="rounded-full px-2 py-1 text-xs font-semibold" style={tagColorStyle()}>{tag}</span>) : "—"}
                    </div>
                  </td>
                  <td className="p-3">{link.funnel_id || "welcome"}</td>
                  <td className="p-3 font-bold">{link.metrics.clicks}</td>
                  <td className="p-3">{link.metrics.new_users}</td>
                  <td className="p-3">{link.metrics.applications}</td>
                  <td className="p-3">{link.metrics.purchases}</td>
                  <td className="p-3">{link.metrics.click_to_application}%</td>
                  <td className="p-3">{formatDate(link.created_at)}</td>
                  <td className="p-3">
                    <button type="button" onClick={() => patch.mutate({ id: link.id, payload: { is_active: !link.is_active } })} className="inline-flex items-center gap-2 text-sm font-semibold">
                      {link.is_active ? <ToggleRight className="text-sage" size={24} /> : <ToggleLeft className="text-clay" size={24} />}
                      {link.is_active ? "Активна" : "Отключена"}
                    </button>
                  </td>
                  <td className="p-3">
                    <div className="flex gap-2">
                      <Button className="h-9 px-3" variant="secondary" type="button" onClick={() => void copy(link.full_url)}><Copy size={15} /></Button>
                      <a className="inline-flex h-9 items-center justify-center rounded-card bg-pearl px-3 text-sm font-semibold text-ink hover:bg-[#ead9cf]" href={link.full_url} target="_blank" rel="noreferrer"><ExternalLink size={15} /></a>
                      <Button className="h-9 px-3" variant="ghost" type="button" onClick={() => setQrUrl(link.full_url)}><QrCode size={15} /></Button>
                      <Button className="h-9 px-3" variant="danger" type="button" onClick={() => remove.mutate(link.id)}><Trash2 size={15} /></Button>
                    </div>
                  </td>
                </tr>
              ))}
              {!links.length ? (
                <tr><td className="p-8 text-center text-clay" colSpan={15}>Ссылок пока нет</td></tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </Card>
      {qrUrl ? (
        <div className="fixed inset-0 z-50 grid place-items-center bg-ink/35 p-4" onClick={() => setQrUrl("")}>
          <div className="rounded-card bg-white p-5 shadow-soft" onClick={(event) => event.stopPropagation()}>
            <img alt="QR code" className="h-64 w-64" src={`https://api.qrserver.com/v1/create-qr-code/?size=256x256&data=${encodeURIComponent(qrUrl)}`} />
            <p className="mt-3 max-w-64 break-all text-center text-xs text-clay">{qrUrl}</p>
          </div>
        </div>
      ) : null}
    </div>
  );
}

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BarChart3, MessageCircleQuestion, MousePointerClick, NotebookText, ShieldCheck, UserPlus, Users } from "lucide-react";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { apiRequest } from "../api/client";
import { Badge, Button, Card, Input, SectionTitle, Select } from "../components/ui";
import { formatDate, statusLabel } from "./crmShared";

type AdminUser = {
  id: number;
  name?: string | null;
  email: string;
  role: "owner" | "admin" | "manager" | "viewer" | string;
  is_active: boolean;
  can_broadcast?: boolean;
  last_login_at?: string | null;
  active_leads?: number;
  processed_leads?: number;
};

type ManagerReportItem = {
  id: number;
  email: string;
  role: string;
  is_active: boolean;
  assigned_leads: number;
  new_leads: number;
  active_leads: number;
  applications: number;
  purchases: number;
  waiting_reply: number;
  in_progress: number;
  warming: number;
  notes_count: number;
  manager_events_count: number;
  application_conversion: number;
  purchase_conversion: number;
  last_activity_at?: string | null;
  status_counts: Record<string, number>;
  funnel_events: Record<string, number>;
};

type ManagerReport = {
  items: ManagerReportItem[];
  totals: Record<string, any>;
  funnel_event_labels: Record<string, string>;
};

function reportQuery(dateFrom: string, dateTo: string) {
  const params = new URLSearchParams();
  if (dateFrom) params.set("date_from", dateFrom);
  if (dateTo) params.set("date_to", dateTo);
  return params.toString();
}

function percent(value?: number) {
  return `${value ?? 0}%`;
}

export function Admins() {
  const qc = useQueryClient();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState("manager");
  const [canBroadcast, setCanBroadcast] = useState(true);
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const periodQuery = reportQuery(dateFrom, dateTo);

  const { data } = useQuery<{ items: AdminUser[] }>({
    queryKey: ["managers"],
    queryFn: () => apiRequest("/api/admin/managers")
  });
  const { data: report } = useQuery<ManagerReport>({
    queryKey: ["manager-report", periodQuery],
    queryFn: () => apiRequest(`/api/admin/crm/managers/report?${periodQuery}`)
  });

  const managers = report?.items || [];
  const totals = report?.totals || {};
  const activeManagers = useMemo(() => managers.filter((item) => item.is_active).length, [managers]);

  const create = useMutation({
    mutationFn: () => apiRequest("/api/admin/managers", { method: "POST", body: JSON.stringify({ name, email, password, role, can_broadcast: canBroadcast }) }),
    onSuccess: () => {
      setName("");
      setEmail("");
      setPassword("");
      setRole("manager");
      setCanBroadcast(true);
      qc.invalidateQueries({ queryKey: ["admins"] });
      qc.invalidateQueries({ queryKey: ["managers"] });
      qc.invalidateQueries({ queryKey: ["manager-report"] });
      qc.invalidateQueries({ queryKey: ["crm-options"] });
    }
  });
  const patch = useMutation({
    mutationFn: ({ id, payload }: { id: number; payload: Record<string, unknown> }) =>
      apiRequest(`/api/admin/managers/${id}`, { method: "PATCH", body: JSON.stringify(payload) }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["managers"] });
      qc.invalidateQueries({ queryKey: ["manager-report"] });
      qc.invalidateQueries({ queryKey: ["crm-options"] });
    }
  });
  const resetPassword = useMutation({
    mutationFn: (id: number) => apiRequest(`/api/admin/managers/${id}/reset-password`, { method: "POST", body: JSON.stringify({ password: "manager12345" }) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["managers"] })
  });

  const statCards = [
    { label: "Активные менеджеры", value: activeManagers, icon: Users },
    { label: "Назначено клиентов", value: totals.assigned_leads ?? 0, icon: UserPlus },
    { label: "Новые за период", value: totals.new_leads ?? 0, icon: BarChart3 },
    { label: "Активные за период", value: totals.active_leads ?? 0, icon: MousePointerClick },
    { label: "Ждут ответа", value: totals.waiting_reply ?? 0, icon: MessageCircleQuestion },
    { label: "Заявки", value: totals.applications ?? 0, icon: NotebookText },
    { label: "Купили", value: totals.purchases ?? 0, icon: ShieldCheck },
    { label: "Конверсия в заявку", value: percent(totals.application_conversion), icon: BarChart3 }
  ];

  return (
    <div>
      <SectionTitle title="Менеджеры" subtitle="Добавление менеджеров, назначение лидов и отчет по работе с CRM" />

      <div className="mb-5 grid gap-3 md:grid-cols-4 xl:grid-cols-8">
        {statCards.map((card) => {
          const Icon = card.icon;
          return (
            <Card key={card.label} className="p-4">
              <div className="mb-2 flex items-center gap-2 text-xs font-semibold text-clay">
                <Icon size={15} />
                {card.label}
              </div>
              <p className="text-xl font-bold text-ink">{card.value}</p>
            </Card>
          );
        })}
      </div>

      <Card className="mb-5">
        <div className="mb-4 flex flex-col justify-between gap-3 md:flex-row md:items-end">
          <div>
            <h2 className="font-bold text-ink">Добавить менеджера</h2>
            <p className="mt-1 text-sm text-clay">Менеджер сможет получать назначенных клиентов и оставлять заметки в карточках лидов.</p>
          </div>
          <div className="grid gap-2 sm:grid-cols-2">
            <Input type="date" value={dateFrom} onChange={(event) => setDateFrom(event.target.value)} />
            <Input type="date" value={dateTo} onChange={(event) => setDateTo(event.target.value)} />
          </div>
        </div>
        <div className="grid gap-3 md:grid-cols-[1fr_1fr_180px_160px_auto]">
          <Input placeholder="имя менеджера" value={name} onChange={(event) => setName(event.target.value)} />
          <Input placeholder="email менеджера" value={email} onChange={(event) => setEmail(event.target.value)} />
          <Input placeholder="пароль" type="password" value={password} onChange={(event) => setPassword(event.target.value)} />
          <Select value={role} onChange={(event) => setRole(event.target.value)}>
            <option value="admin">admin</option>
            <option value="manager">manager</option>
            <option value="owner">owner</option>
            <option value="viewer">viewer</option>
          </Select>
          <Button onClick={() => create.mutate()} disabled={!email || !password || create.isPending}>
            <UserPlus size={16} />
            Добавить
          </Button>
        </div>
        <label className="mt-3 inline-flex items-center gap-2 text-sm text-clay">
          <input type="checkbox" checked={canBroadcast} onChange={(event) => setCanBroadcast(event.target.checked)} />
          Разрешить запуск рассылок
        </label>
      </Card>

      <Card className="mb-5 overflow-hidden p-0">
        <div className="border-b border-pearl bg-white/50 p-4">
          <h2 className="font-bold text-ink">Отчет по менеджерам</h2>
          <p className="mt-1 text-sm text-clay">Период влияет на новые лиды, активность, заметки и клики воронки. Назначенные, заявки и покупки считаются по текущему состоянию CRM.</p>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[1220px] text-sm">
            <thead className="bg-pearl/60 text-left text-clay">
              <tr>
                <th className="p-3">Менеджер</th>
                <th className="p-3">Клиенты</th>
                <th className="p-3">Статусы</th>
                <th className="p-3">Действия воронки</th>
                <th className="p-3">Работа менеджера</th>
                <th className="p-3">Конверсия</th>
                <th className="p-3">Активность</th>
                <th className="p-3"></th>
              </tr>
            </thead>
            <tbody>
              {managers.map((manager) => (
                <tr key={manager.id} className="border-t border-pearl align-top hover:bg-milk/70">
                  <td className="p-3">
                    <p className="font-bold text-ink">{manager.email}</p>
                    <div className="mt-2 flex flex-wrap gap-1">
                      <Badge>{manager.role}</Badge>
                      <Badge tone={manager.is_active ? "green" : "red"}>{manager.is_active ? "активен" : "отключен"}</Badge>
                    </div>
                  </td>
                  <td className="p-3">
                    <p><b>{manager.assigned_leads}</b> назначено</p>
                    <p className="text-clay"><b>{manager.new_leads}</b> новых за период</p>
                    <p className="text-clay"><b>{manager.active_leads}</b> активных за период</p>
                  </td>
                  <td className="p-3">
                    <div className="grid gap-1">
                      <span>{statusLabel("manual_contact")}: <b>{manager.waiting_reply}</b></span>
                      <span>{statusLabel("in_dialog")}: <b>{manager.in_progress}</b></span>
                      <span>{statusLabel("thinking")}: <b>{manager.warming}</b></span>
                      <span>{statusLabel("cta_clicked")}: <b>{manager.applications}</b></span>
                      <span>{statusLabel("paid")}: <b>{manager.purchases}</b></span>
                    </div>
                  </td>
                  <td className="p-3">
                    <div className="grid gap-1">
                      <span>Тренировка: <b>{manager.funnel_events.training_requested || 0}</b></span>
                      <span>Вопросы: <b>{manager.funnel_events.questions_clicked || 0}</b></span>
                      <span>Купить: <b>{manager.funnel_events.course_buy_clicked || 0}</b></span>
                      <span>Рассрочка: <b>{manager.funnel_events.installment_clicked || 0}</b></span>
                    </div>
                  </td>
                  <td className="p-3">
                    <p>Заметки: <b>{manager.notes_count}</b></p>
                    <p className="text-clay">Изменения/события: <b>{manager.manager_events_count}</b></p>
                  </td>
                  <td className="p-3">
                    <p>В заявку: <b>{percent(manager.application_conversion)}</b></p>
                    <p className="text-clay">В покупку: <b>{percent(manager.purchase_conversion)}</b></p>
                  </td>
                  <td className="p-3 text-clay">{formatDate(manager.last_activity_at)}</td>
                  <td className="p-3">
                    <Link to={`/admin/crm?manager_id=${manager.id}`} className="inline-flex h-9 items-center justify-center rounded-card bg-pearl px-3 text-sm font-semibold text-ink hover:bg-[#ead9cf]">
                      Открыть CRM
                    </Link>
                  </td>
                </tr>
              ))}
              {!managers.length ? (
                <tr>
                  <td className="p-8 text-center text-clay" colSpan={8}>Менеджеры не найдены</td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </Card>

      <Card className="overflow-hidden p-0">
        <div className="border-b border-pearl bg-white/50 p-4">
          <h2 className="font-bold text-ink">Доступы</h2>
          <p className="mt-1 text-sm text-clay">Owner управляет ролями и может отключить доступ без удаления истории работы.</p>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[780px] text-sm">
            <thead className="bg-pearl/60 text-left text-clay">
              <tr>
                <th className="p-4">Менеджер</th>
                <th className="p-4">Роль</th>
                <th className="p-4">Рассылки</th>
                <th className="p-4">Last login</th>
                <th className="p-4">Статус</th>
                <th className="p-4">Действия</th>
              </tr>
            </thead>
            <tbody>
              {(data?.items || []).map((admin) => (
                <tr key={admin.id} className="border-t border-pearl">
                  <td className="p-4">
                    <p className="font-semibold">{admin.name || admin.email}</p>
                    <p className="text-xs text-clay">{admin.email}</p>
                    <p className="text-xs text-clay">{admin.active_leads || 0} в работе · {admin.processed_leads || 0} обработано</p>
                  </td>
                  <td className="p-4">
                    <Select className="max-w-44" value={admin.role} onChange={(event) => patch.mutate({ id: admin.id, payload: { role: event.target.value } })}>
                      <option value="owner">owner</option>
                      <option value="admin">admin</option>
                      <option value="manager">manager</option>
                      <option value="viewer">viewer</option>
                    </Select>
                  </td>
                  <td className="p-4">
                    <label className="inline-flex items-center gap-2">
                      <input type="checkbox" checked={Boolean(admin.can_broadcast)} onChange={(event) => patch.mutate({ id: admin.id, payload: { can_broadcast: event.target.checked } })} />
                      allowed
                    </label>
                  </td>
                  <td className="p-4 text-clay">{formatDate(admin.last_login_at)}</td>
                  <td className="p-4">
                    <Badge tone={admin.is_active ? "green" : "red"}>{admin.is_active ? "активен" : "отключен"}</Badge>
                  </td>
                  <td className="p-4">
                    <Button
                      variant="secondary"
                      onClick={() => patch.mutate({ id: admin.id, payload: { is_active: !admin.is_active } })}
                    >
                      {admin.is_active ? "Отключить" : "Включить"}
                    </Button>
                    <Button className="ml-2" variant="ghost" onClick={() => resetPassword.mutate(admin.id)}>
                      Reset pass
                    </Button>
                  </td>
                </tr>
              ))}
              {!data?.items?.length ? (
                <tr>
                  <td className="p-8 text-center text-clay" colSpan={6}>Доступы не найдены</td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}

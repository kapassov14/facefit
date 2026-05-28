import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, BarChart3, CheckCircle2, Database, MousePointerClick, UserMinus, Users } from "lucide-react";
import { Bar, BarChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Link } from "react-router-dom";
import { useState } from "react";

import { apiRequest } from "../api/client";
import { Card, SectionTitle, Select } from "../components/ui";
import { CrmStatusBadge, formatDate } from "./crmShared";

const periods = [
  { value: "today", label: "Сегодня" },
  { value: "7d", label: "7 дней" },
  { value: "30d", label: "30 дней" },
  { value: "all", label: "Весь период" }
];

export function Dashboard() {
  const [period, setPeriod] = useState("7d");
  const { data: stats, isLoading } = useQuery({ queryKey: ["admin-dashboard-stats", period], queryFn: () => apiRequest<any>(`/api/admin/dashboard/stats?period=${period}`) });
  const { data: funnel } = useQuery({ queryKey: ["admin-dashboard-funnel", period], queryFn: () => apiRequest<any>(`/api/admin/dashboard/funnel?period=${period}`) });
  const { data: charts } = useQuery({ queryKey: ["admin-dashboard-charts", period], queryFn: () => apiRequest<any>(`/api/admin/dashboard/charts?period=${period}`) });
  const cards = stats?.cards || {};
  const metricCards = [
    ["Активные пользователи", cards.active_users, Users, cards.period_new_users?.delta_percent ? `${cards.period_new_users.delta_percent}% за период` : "без изменения"],
    ["Отписались / заблокировали", cards.blocked_or_unsubscribed, UserMinus, `${cards.blocked_percent || 0}% базы`],
    ["Всего пользователей", cards.total_users, Users, `сегодня +${cards.new_users_today || 0}`],
    ["Новые пользователи", cards.period_new_users?.total, MousePointerClick, `7д +${cards.new_users_7d || 0} · 30д +${cards.new_users_30d || 0}`],
    ["Базы", cards.bases_count, Database, `${cards.total_memberships || 0} membership`],
    ["Unique users in bases", cards.unique_users_in_bases, Database, "без дублей"],
    ["Завершенные анализы", cards.completed_analyses, CheckCircle2, "completed AnalysisRequest"],
    ["Заявки в работе", cards.active_leads, BarChart3, "активная CRM"],
    ["AI / review errors", (cards.ai_errors || 0) + (cards.needs_manual_review || 0), AlertTriangle, `${cards.ai_errors || 0} failed · ${cards.needs_manual_review || 0} review`]
  ];
  return (
    <div>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <SectionTitle title="Dashboard" subtitle="Операционная картина: пользователи, базы, анализы, CRM и воронка" />
        <Select className="w-44" value={period} onChange={(event) => setPeriod(event.target.value)}>
          {periods.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
        </Select>
      </div>
      {isLoading ? <p className="text-sm text-clay">Загружаю...</p> : null}
      <div className="grid gap-4 md:grid-cols-3 xl:grid-cols-5">
        {metricCards.map(([label, value, Icon, hint]) => (
          <Card key={String(label)} className="p-4">
            <div className="flex items-center justify-between">
              <p className="text-xs font-semibold text-clay">{String(label)}</p>
              <Icon className="text-rose" size={18} />
            </div>
            <p className="mt-3 text-2xl font-bold">{String(value ?? 0)}</p>
            <p className="mt-1 text-xs text-clay">{String(hint)}</p>
          </Card>
        ))}
      </div>
      <div className="mt-6 grid gap-5 xl:grid-cols-2">
        <Card>
          <h2 className="mb-4 font-bold">Пользователи по дням</h2>
          <div className="h-72">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={charts?.users_by_day || []}>
                <CartesianGrid stroke="#eadbd1" />
                <XAxis dataKey="date" />
                <YAxis allowDecimals={false} />
                <Tooltip />
                <Line type="monotone" dataKey="count" stroke="#be7d86" strokeWidth={3} dot={{ r: 3 }} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </Card>
        <Card>
          <h2 className="mb-4 font-bold">Анализы по дням</h2>
          <div className="h-72">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={charts?.analyses_by_day || []}>
                <CartesianGrid stroke="#eadbd1" />
                <XAxis dataKey="date" />
                <YAxis allowDecimals={false} />
                <Tooltip />
                <Line type="monotone" dataKey="count" stroke="#7b967c" strokeWidth={3} dot={{ r: 3 }} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </Card>
      </div>
      <div className="mt-6 grid gap-5 xl:grid-cols-[1fr_1fr_1.1fr]">
        <Card>
          <h2 className="mb-4 font-bold">Воронка</h2>
          <div className="space-y-3">
            {(funnel?.items || []).map((item: any) => (
              <div key={item.key}>
                <div className="mb-1 flex justify-between text-sm">
                  <span className="font-semibold">{item.label}</span>
                  <span className="text-clay">{item.count} · {item.from_previous_percent}%</span>
                </div>
                <div className="h-2 rounded-full bg-pearl">
                  <div className="h-2 rounded-full bg-rose" style={{ width: `${Math.min(item.from_start_percent || 0, 100)}%` }} />
                </div>
              </div>
            ))}
          </div>
        </Card>
        <Card>
          <h2 className="mb-4 font-bold">Топ проблем</h2>
          <div className="h-72">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={charts?.top_problems || []}>
                <XAxis dataKey="title" hide />
                <YAxis allowDecimals={false} />
                <Tooltip />
                <Bar dataKey="count" fill="#be7d86" radius={[6, 6, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Card>
        <Card>
          <h2 className="mb-4 font-bold">Последние лиды</h2>
          <div className="space-y-3">
            {(stats?.latest_leads || []).map((lead: any) => (
              <Link key={lead.id} to={`/admin/crm?lead=${lead.id}`} className="block rounded-card border border-pearl p-3 hover:bg-milk">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="font-semibold">{lead.name || lead.telegram_user?.username || "Без имени"}</p>
                    <p className="mt-1 text-xs text-clay">{formatDate(lead.last_activity_at)} · {(lead.selected_problems || []).join(", ") || "нет проблем"}</p>
                  </div>
                  <CrmStatusBadge status={lead.status} />
                </div>
              </Link>
            ))}
          </div>
        </Card>
      </div>
      <div className="mt-6 grid gap-5 xl:grid-cols-2">
        <Card>
          <h2 className="mb-4 font-bold">Топ источников</h2>
          <div className="space-y-2">
            {(charts?.top_sources || []).map((item: any) => (
              <div key={item.source} className="flex items-center justify-between rounded-card bg-milk px-3 py-2 text-sm">
                <span>{item.source}</span>
                <b>{item.count}</b>
              </div>
            ))}
          </div>
        </Card>
      </div>
    </div>
  );
}

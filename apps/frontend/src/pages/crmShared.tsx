import { Badge } from "../components/ui";

export const CRM_STATUSES = [
  { value: "new", label: "Новый" },
  { value: "warming", label: "В прогреве" },
  { value: "applied", label: "Оставил заявку" },
  { value: "waiting_reply", label: "Ждет ответа" },
  { value: "in_progress", label: "В работе" },
  { value: "bought", label: "Купил" },
  { value: "rejected", label: "Отказ" },
  { value: "no_answer", label: "Не отвечает" },
  { value: "archived", label: "Архив" }
];

export function statusLabel(value?: string) {
  return CRM_STATUSES.find((item) => item.value === value)?.label || value || "Новый";
}

export function statusTone(value?: string): "green" | "yellow" | "red" | "neutral" {
  if (value === "bought") return "green";
  if (value === "applied" || value === "waiting_reply" || value === "in_progress") return "yellow";
  if (value === "rejected" || value === "no_answer" || value === "archived") return "red";
  return "neutral";
}

export function CrmStatusBadge({ status }: { status?: string }) {
  return <Badge tone={statusTone(status)}>{statusLabel(status)}</Badge>;
}

export function formatDate(value?: string | null) {
  if (!value) return "—";
  return new Intl.DateTimeFormat("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    year: "2-digit",
    hour: "2-digit",
    minute: "2-digit"
  }).format(new Date(value));
}

export function tagColorStyle(color?: string) {
  return {
    backgroundColor: color || "#f2e7de",
    color: "#3e3631"
  };
}

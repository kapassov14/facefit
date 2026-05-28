import { Badge } from "../components/ui";

export const CRM_STATUSES = [
  { value: "new", label: "Новый лид" },
  { value: "photo_sent", label: "Отправил фото" },
  { value: "protocol_sent", label: "Получил протокол" },
  { value: "report_opened", label: "Открыл отчет" },
  { value: "cta_clicked", label: "Нажал CTA" },
  { value: "manual_contact", label: "Написать вручную" },
  { value: "in_dialog", label: "В диалоге" },
  { value: "thinking", label: "Думает" },
  { value: "paid", label: "Оплатил" },
  { value: "not_relevant", label: "Не актуально" },
  { value: "archived", label: "Архив" }
];

export function statusLabel(value?: string) {
  return CRM_STATUSES.find((item) => item.value === value)?.label || value || "Новый";
}

export function statusTone(value?: string): "green" | "yellow" | "red" | "neutral" {
  if (value === "paid") return "green";
  if (value === "cta_clicked" || value === "manual_contact" || value === "in_dialog" || value === "thinking") return "yellow";
  if (value === "not_relevant" || value === "archived") return "red";
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

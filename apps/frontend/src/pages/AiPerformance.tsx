import { useQuery } from "@tanstack/react-query";
import { Gauge } from "lucide-react";

import { apiRequest } from "../api/client";
import { Badge, Card, SectionTitle } from "../components/ui";
import { formatDate } from "./crmShared";

type PerfRow = {
  id: number;
  analysis_id?: number;
  stage: string;
  status: string;
  provider?: string;
  analysis_provider?: string;
  image_provider?: string;
  analysis_time_ms?: number;
  image_time_ms?: number;
  report_build_time_ms?: number;
  telegram_send_time_ms?: number;
  total_processing_time_ms?: number;
  error_message?: string;
  created_at?: string;
};
type PerfSummary = {
  provider: string;
  count: number;
  errors: number;
  avg_analysis_time_ms: number;
  avg_image_time_ms: number;
  avg_total_processing_time_ms: number;
};

export function AiPerformance() {
  const { data } = useQuery<{ summary: PerfSummary[]; items: PerfRow[] }>({
    queryKey: ["ai-performance"],
    queryFn: () => apiRequest("/api/admin/ai-performance")
  });
  const summary = data?.summary || [];
  const rows = data?.items || [];
  return (
    <div>
      <SectionTitle title="AI latency" subtitle="Сравнение OpenAI и Gemini по скорости, ошибкам и fallback" />
      <div className="mb-5 grid gap-3 md:grid-cols-3">
        {summary.map((item) => (
          <Card key={item.provider} className="p-4">
            <div className="flex items-center justify-between">
              <p className="font-bold">{item.provider}</p>
              <Gauge size={18} className="text-clay" />
            </div>
            <div className="mt-4 grid grid-cols-2 gap-3 text-sm">
              <p><span className="text-clay">Анализ</span><br /><b>{item.avg_analysis_time_ms} ms</b></p>
              <p><span className="text-clay">Фото</span><br /><b>{item.avg_image_time_ms} ms</b></p>
              <p><span className="text-clay">Total</span><br /><b>{item.avg_total_processing_time_ms} ms</b></p>
              <p><span className="text-clay">Ошибки</span><br /><b>{item.errors}</b></p>
            </div>
          </Card>
        ))}
        {!summary.length ? <Card className="p-4 text-sm text-clay">Логи появятся после первой обработки.</Card> : null}
      </div>
      <Card className="overflow-hidden p-0">
        <table className="w-full min-w-[980px] text-sm">
          <thead className="bg-pearl/60 text-left text-clay">
            <tr>
              <th className="p-3">Время</th>
              <th className="p-3">Job</th>
              <th className="p-3">Stage</th>
              <th className="p-3">Provider</th>
              <th className="p-3">Analysis</th>
              <th className="p-3">Image</th>
              <th className="p-3">Report</th>
              <th className="p-3">Telegram</th>
              <th className="p-3">Total</th>
              <th className="p-3">Status</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.id} className="border-t border-pearl">
                <td className="p-3">{formatDate(row.created_at)}</td>
                <td className="p-3">#{row.analysis_id || "—"}</td>
                <td className="p-3">{row.stage}</td>
                <td className="p-3">{row.analysis_provider || row.image_provider || row.provider || "—"}</td>
                <td className="p-3">{row.analysis_time_ms ?? "—"}</td>
                <td className="p-3">{row.image_time_ms ?? "—"}</td>
                <td className="p-3">{row.report_build_time_ms ?? "—"}</td>
                <td className="p-3">{row.telegram_send_time_ms ?? "—"}</td>
                <td className="p-3">{row.total_processing_time_ms ?? "—"}</td>
                <td className="p-3"><Badge tone={row.status === "failed" ? "red" : "green"}>{row.status}</Badge></td>
              </tr>
            ))}
            {!rows.length ? <tr><td className="p-8 text-center text-clay" colSpan={10}>Пока нет latency logs</td></tr> : null}
          </tbody>
        </table>
      </Card>
    </div>
  );
}

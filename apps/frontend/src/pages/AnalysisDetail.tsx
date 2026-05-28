import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { RefreshCcw } from "lucide-react";
import { Link, useParams } from "react-router-dom";

import { apiRequest, storageUrl } from "../api/client";
import { JsonViewer } from "../components/JsonViewer";
import { StatusBadge } from "../components/StatusBadge";
import { Button, Card, SectionTitle } from "../components/ui";

export function AnalysisDetail() {
  const { id } = useParams();
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["analysis", id], queryFn: () => apiRequest<any>(`/api/analysis/${id}`), enabled: Boolean(id) });
  const action = useMutation({
    mutationFn: (path: string) => apiRequest(`/api/analysis/${id}/${path}`, { method: "POST" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["analysis", id] })
  });
  if (!data) return <p>Загружаю...</p>;
  return (
    <div>
      <SectionTitle title={`Анализ #${data.id}`} subtitle={data.lead?.name || "Без имени"} />
      <div className="mb-5 flex flex-wrap gap-2">
        <StatusBadge status={data.status} />
        <Button variant="secondary" onClick={() => action.mutate("retry")}><RefreshCcw size={16} />Перегенерировать анализ</Button>
        <Button variant="secondary" onClick={() => action.mutate("regenerate-personal-insights")}>Перегенерировать personal insights</Button>
        <Button variant="secondary" onClick={() => action.mutate("regenerate-protocol-copy")}>Перегенерировать protocol copy</Button>
        <Button variant="secondary" onClick={() => action.mutate("regenerate-face-protocol")}>Перегенерировать face protocol PNG</Button>
        <Button variant="secondary" onClick={() => action.mutate("regenerate-report")}>Перегенерировать отчет</Button>
        {data.report_token ? <Link to={`/report/${data.report_token}`} target="_blank"><Button type="button">Открыть отчет</Button></Link> : null}
      </div>
      {data.error_message ? <Card className="mb-5 border-red-200 bg-red-50 text-red-900">{data.error_message}</Card> : null}
      <div className="grid gap-5 xl:grid-cols-[420px_1fr]">
        <div className="space-y-5">
          <Card>
            <h2 className="mb-3 font-bold">Заявка</h2>
            <div className="space-y-2 text-sm">
              <p><span className="font-semibold">Выбранные зоны:</span> {(data.selected_problems || []).join(", ") || "не указаны"}</p>
              <p><span className="font-semibold">Public report:</span> {data.report_token ? <Link className="text-brand underline" to={`/report/${data.report_token}`} target="_blank">{data.report_token}</Link> : "не готов"}</p>
            </div>
          </Card>
          <Card>
            <h2 className="mb-3 font-bold">Изображения</h2>
            <div className="grid gap-3">
              <div>
                <p className="mb-1 text-xs font-semibold text-clay">Final face protocol PNG {data.face_protocol_version || data.protocol_version || "не готов"}</p>
                {data.face_protocol_image_path ? (
                  <img src={storageUrl(data.face_protocol_image_path)} alt="Final face protocol" className="w-full rounded-card border border-pearl object-cover" />
                ) : data.protocol_slide_paths?.length ? (
                  <div className="grid gap-2">
                    {data.protocol_slide_paths.map((path: string, index: number) => (
                      <img key={path} src={storageUrl(path)} alt={`Protocol slide ${index + 1}`} className="w-full rounded-card border border-pearl object-cover" />
                    ))}
                  </div>
                ) : (
                  <p className="text-sm text-clay">Еще не готово</p>
                )}
              </div>
              {[
                ["Исходное", data.original_photo_path],
                ["Legacy фото-протокол", data.legacy_protocol_image_path]
              ].map(([label, path]) => (
                <div key={label}>
                  <p className="mb-1 text-xs font-semibold text-clay">{label}</p>
                  {path ? <img src={storageUrl(String(path))} className="w-full rounded-card border border-pearl object-cover" /> : <p className="text-sm text-clay">Еще не готово</p>}
                </div>
              ))}
            </div>
          </Card>
          <Card>
            <h2 className="mb-3 font-bold">AI логи</h2>
            <div className="space-y-3">
              {(data.ai_logs || []).map((log: any) => (
                <div key={log.id} className="rounded-card border border-pearl p-3 text-sm">
                  <p className="font-semibold">{log.stage} · {log.status}</p>
                  <p className="text-clay">{log.message}</p>
                </div>
              ))}
            </div>
          </Card>
        </div>
        <div className="space-y-5">
          <Card>
            <h2 className="mb-3 font-bold">JSON-анализ</h2>
            <JsonViewer value={data.analysis_json} />
          </Card>
          <Card>
            <h2 className="mb-3 font-bold">Personal insight JSON</h2>
            <JsonViewer value={data.personal_insight_json} />
          </Card>
          <Card>
            <h2 className="mb-3 font-bold">Protocol copy JSON</h2>
            <JsonViewer value={data.protocol_copy_json} />
          </Card>
          <Card>
            <h2 className="mb-3 font-bold">Report JSON</h2>
            <JsonViewer value={data.report_json} />
          </Card>
        </div>
      </div>
    </div>
  );
}

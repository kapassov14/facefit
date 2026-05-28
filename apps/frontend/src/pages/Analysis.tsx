import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { apiRequest, storageUrl } from "../api/client";
import { StatusBadge } from "../components/StatusBadge";
import { Card, SectionTitle } from "../components/ui";

export function Analysis() {
  const { data } = useQuery({ queryKey: ["analysis"], queryFn: () => apiRequest<any>("/api/analysis") });
  return (
    <div>
      <SectionTitle title="Заявки / Анализы" subtitle="Исходные фото, JSON, протоколы, отчеты и AI-логи" />
      <div className="grid gap-4">
        {(data?.items || []).map((item: any) => (
          <Link key={item.id} to={`/admin/analysis/${item.id}`}>
            <Card className="grid gap-4 md:grid-cols-[96px_1fr_auto] md:items-center">
              <img src={storageUrl(item.original_photo_path)} className="h-24 w-24 rounded-card object-cover" />
              <div>
                <p className="font-bold">Анализ #{item.id} · {item.lead?.name || "Без имени"}</p>
                <p className="mt-1 text-sm text-clay">{(item.selected_problems || []).join(", ")}</p>
                {item.report_token ? <p className="mt-1 text-xs text-sage">report/{item.report_token}</p> : null}
              </div>
              <StatusBadge status={item.status} />
            </Card>
          </Link>
        ))}
      </div>
    </div>
  );
}

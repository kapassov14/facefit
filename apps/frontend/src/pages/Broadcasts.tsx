import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Pause, Play, Send, Square, TestTube2 } from "lucide-react";
import { useState } from "react";
import { useSearchParams } from "react-router-dom";

import { apiRequest } from "../api/client";
import { Badge, Button, Card, Input, SectionTitle, Select, Textarea } from "../components/ui";
import { formatDate } from "./crmShared";

export function Broadcasts() {
  const qc = useQueryClient();
  const [params] = useSearchParams();
  const { data } = useQuery({ queryKey: ["broadcasts"], queryFn: () => apiRequest<any>("/api/admin/broadcasts") });
  const { data: bases } = useQuery({ queryKey: ["bases"], queryFn: () => apiRequest<any>("/api/admin/bases?page_size=100") });
  const [title, setTitle] = useState("");
  const [text, setText] = useState("");
  const [baseId, setBaseId] = useState(params.get("base_id") || "");
  const [buttonText, setButtonText] = useState("");
  const [buttonUrl, setButtonUrl] = useState("");
  const [rate, setRate] = useState("10");
  const [testTelegramId, setTestTelegramId] = useState("");
  const create = useMutation({
    mutationFn: () => apiRequest("/api/admin/broadcasts", {
      method: "POST",
      body: JSON.stringify({
        title,
        base_id: baseId ? Number(baseId) : null,
        message_type: "text",
        message_text: text,
        text,
        buttons_json: buttonText && buttonUrl ? [{ text: buttonText, url: buttonUrl }] : [],
        buttons: buttonText && buttonUrl ? [{ text: buttonText, url: buttonUrl }] : [],
        rate_limit_per_second: Number(rate || 10)
      })
    }),
    onSuccess: () => {
      setTitle("");
      setText("");
      setButtonText("");
      setButtonUrl("");
      qc.invalidateQueries({ queryKey: ["broadcasts"] });
    }
  });
  const send = useMutation({
    mutationFn: (id: number) => apiRequest(`/api/admin/broadcasts/${id}/send`, { method: "POST" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["broadcasts"] })
  });
  const pause = useMutation({
    mutationFn: (id: number) => apiRequest(`/api/admin/broadcasts/${id}/pause`, { method: "POST" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["broadcasts"] })
  });
  const cancel = useMutation({
    mutationFn: (id: number) => apiRequest(`/api/admin/broadcasts/${id}/cancel`, { method: "POST" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["broadcasts"] })
  });
  const testSend = useMutation({
    mutationFn: (id: number) => apiRequest(`/api/admin/broadcasts/${id}/test-send`, { method: "POST", body: JSON.stringify({ telegram_id: Number(testTelegramId) }) })
  });
  const selectedBase = (bases?.items || []).find((item: any) => String(item.id) === String(baseId));
  return (
    <div>
      <SectionTitle title="Рассылки" subtitle="Composer, preview, тестовая отправка и очередь Telegram" />
      <div className="grid gap-5 xl:grid-cols-[420px_1fr]">
        <Card>
          <h2 className="mb-4 font-bold">Новая рассылка</h2>
          <div className="space-y-3">
            <Input placeholder="Название" value={title} onChange={(e) => setTitle(e.target.value)} />
            <Select value={baseId} onChange={(e) => setBaseId(e.target.value)}>
              <option value="">Выберите базу</option>
              {(bases?.items || []).map((item: any) => <option key={item.id} value={item.id}>{item.name} · {item.members_count}</option>)}
            </Select>
            <Textarea placeholder="Текст сообщения" value={text} onChange={(e) => setText(e.target.value)} />
            <div className="grid gap-2 md:grid-cols-2">
              <Input placeholder="Текст кнопки" value={buttonText} onChange={(e) => setButtonText(e.target.value)} />
              <Input placeholder="https://..." value={buttonUrl} onChange={(e) => setButtonUrl(e.target.value)} />
            </div>
            <Select value={rate} onChange={(e) => setRate(e.target.value)}>
              <option value="5">5 msg/sec</option>
              <option value="10">10 msg/sec</option>
              <option value="15">15 msg/sec</option>
            </Select>
            <div className="rounded-card border border-pearl bg-milk p-4 text-sm">
              <p className="mb-2 font-semibold text-clay">Telegram preview</p>
              <p className="whitespace-pre-wrap">{text || "Текст рассылки появится здесь"}</p>
              {buttonText ? <span className="mt-3 inline-flex rounded-card bg-white px-3 py-2 font-semibold text-rose">{buttonText}</span> : null}
              <p className="mt-3 text-xs text-clay">Получателей: {selectedBase?.active_users ?? 0} активных · исключено {selectedBase?.blocked_or_unsubscribed ?? 0}</p>
            </div>
            <Button onClick={() => create.mutate()} disabled={!title.trim() || !text.trim() || !baseId}>Создать draft</Button>
          </div>
        </Card>
        <Card>
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
            <h2 className="font-bold">История</h2>
            <div className="flex items-center gap-2">
              <Input className="w-52" value={testTelegramId} onChange={(event) => setTestTelegramId(event.target.value)} placeholder="Telegram ID для test" />
            </div>
          </div>
          <div className="space-y-3">
            {(data?.items || []).map((item: any) => {
              const counts = item.recipient_counts || {};
              return (
                <div key={item.id} className="rounded-card border border-pearl p-4">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <div className="flex flex-wrap items-center gap-2">
                        <p className="font-bold">{item.title}</p>
                        <Badge tone={item.status === "completed" ? "green" : item.status === "failed" ? "red" : "yellow"}>{item.status}</Badge>
                      </div>
                      <p className="mt-1 text-xs text-clay">{item.base?.name || "Без базы"} · {formatDate(item.created_at)} · скорость {item.rate_limit_per_second || 10}/sec</p>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      <Button variant="secondary" disabled={!testTelegramId} onClick={() => testSend.mutate(item.id)}><TestTube2 size={16} />Test</Button>
                      <Button variant="secondary" disabled={["sending", "completed"].includes(item.status)} onClick={() => send.mutate(item.id)}><Send size={16} />Send</Button>
                      <Button variant="ghost" onClick={() => pause.mutate(item.id)}><Pause size={16} /></Button>
                      <Button variant="danger" onClick={() => cancel.mutate(item.id)}><Square size={16} /></Button>
                    </div>
                  </div>
                  <p className="mt-3 whitespace-pre-wrap text-sm">{item.message_text || item.text}</p>
                  <div className="mt-3 flex flex-wrap gap-2 text-xs">
                    {["pending", "sent", "mock_sent", "failed", "blocked", "skipped_unsubscribed"].map((key) => <Badge key={key} tone={key === "sent" || key === "mock_sent" ? "green" : key === "failed" || key === "blocked" ? "red" : "neutral"}>{key}: {counts[key] || 0}</Badge>)}
                  </div>
                  {item.started_at || item.completed_at ? <p className="mt-2 text-xs text-clay">started {formatDate(item.started_at)} · completed {formatDate(item.completed_at)}</p> : null}
                </div>
              );
            })}
            {!data?.items?.length ? <p className="text-sm text-clay">Рассылок пока нет</p> : null}
          </div>
        </Card>
      </div>
    </div>
  );
}

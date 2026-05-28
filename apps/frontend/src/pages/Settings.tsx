import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { apiRequest } from "../api/client";
import { Badge, Button, Card, Input, SectionTitle, Textarea } from "../components/ui";

export function Settings() {
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["settings"], queryFn: () => apiRequest<any>("/api/settings") });
  const [form, setForm] = useState<any>({});
  useEffect(() => {
    if (data) setForm(data);
  }, [data]);
  const mutation = useMutation({
    mutationFn: () => apiRequest("/api/settings", { method: "PATCH", body: JSON.stringify(form) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["settings"] })
  });
  const set = (key: string, value: any) => setForm((prev: any) => ({ ...prev, [key]: value }));
  return (
    <div>
      <SectionTitle title="Настройки" subtitle="Тексты бота, CTA, moderation, лимиты и статус AI ключей" />
      <div className="grid gap-5 lg:grid-cols-[1fr_360px]">
        <Card>
          <div className="grid gap-4">
            {[
              ["welcome_text", "Приветственный текст"],
              ["consent_text", "Текст согласия"],
              ["photo_instruction_text", "Инструкция по фото"],
              ["waiting_text", "Текст ожидания"],
              ["after_analysis_text", "Текст после анализа"],
              ["disclaimer", "Disclaimer"]
            ].map(([key, label]) => (
              <label key={key} className="block">
                <span className="mb-1 block text-xs font-semibold text-clay">{label}</span>
                <Textarea value={form[key] || ""} onChange={(event) => set(key, event.target.value)} />
              </label>
            ))}
            <div className="grid gap-3 md:grid-cols-2">
              <label><span className="mb-1 block text-xs font-semibold text-clay">CTA</span><Input value={form.cta_text || ""} onChange={(e) => set("cta_text", e.target.value)} /></label>
              <label><span className="mb-1 block text-xs font-semibold text-clay">Лимит анализов</span><Input type="number" value={form.analysis_limit_per_user || 0} onChange={(e) => set("analysis_limit_per_user", Number(e.target.value))} /></label>
              <label><span className="mb-1 block text-xs font-semibold text-clay">Instagram</span><Input value={form.instagram_url || ""} onChange={(e) => set("instagram_url", e.target.value)} /></label>
              <label><span className="mb-1 block text-xs font-semibold text-clay">WhatsApp</span><Input value={form.whatsapp_url || ""} onChange={(e) => set("whatsapp_url", e.target.value)} /></label>
              <label><span className="mb-1 block text-xs font-semibold text-clay">Telegram</span><Input value={form.telegram_url || ""} onChange={(e) => set("telegram_url", e.target.value)} /></label>
            </div>
            <div className="flex flex-wrap gap-4">
              {[
                ["manual_moderation_enabled", "Ручная модерация"],
                ["regeneration_enabled", "Повторная генерация"]
              ].map(([key, label]) => (
                <label key={key} className="flex items-center gap-2 rounded-card bg-pearl/60 px-3 py-2 text-sm font-semibold">
                  <input type="checkbox" checked={Boolean(form[key])} onChange={(e) => set(key, e.target.checked)} />
                  {label}
                </label>
              ))}
            </div>
            <Button onClick={() => mutation.mutate()}>Сохранить настройки</Button>
          </div>
        </Card>
        <Card>
          <h2 className="mb-4 font-bold">AI статус</h2>
          <div className="space-y-3 text-sm">
            <p>OpenAI API key: <Badge tone={form.ai_key_status?.openai_api_key ? "green" : "yellow"}>{form.ai_key_status?.openai_api_key ? "подключен" : "mock"}</Badge></p>
            <p>Gemini API key: <Badge tone={form.ai_key_status?.gemini_api_key ? "green" : "neutral"}>{form.ai_key_status?.gemini_api_key ? "подключен" : "нет"}</Badge></p>
            <p>Replicate token: <Badge tone={form.ai_key_status?.replicate_api_token ? "green" : "yellow"}>{form.ai_key_status?.replicate_api_token ? "подключен" : "mock"}</Badge></p>
            <p className="text-clay">Модели задаются только через .env.</p>
          </div>
          <pre className="mt-4 rounded-card bg-milk p-3 text-xs">{JSON.stringify(form.ai_key_status?.models || {}, null, 2)}</pre>
        </Card>
      </div>
    </div>
  );
}

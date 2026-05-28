import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { apiRequest } from "../api/client";
import { Button, Card, SectionTitle, Textarea } from "../components/ui";

export function PromptTemplates() {
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["prompts"], queryFn: () => apiRequest<any>("/api/prompts") });
  const [selected, setSelected] = useState<any | null>(null);
  const [content, setContent] = useState("");
  useEffect(() => {
    const items = (data?.items || []).filter((item: any) => !String(item.key || "").startsWith("after_photo"));
    if ((!selected || String(selected.key || "").startsWith("after_photo")) && items.length) {
      setSelected(items[0]);
      setContent(items[0].content);
    }
  }, [data, selected]);
  const mutation = useMutation({
    mutationFn: () => apiRequest(`/api/prompts/${selected.id}`, { method: "PATCH", body: JSON.stringify({ content }) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["prompts"] })
  });
  return (
    <div>
      <SectionTitle title="Конструктор промптов" subtitle="System prompt, protocol/report prompts и disclaimer" />
      <div className="grid gap-5 lg:grid-cols-[360px_1fr]">
        <Card>
          <div className="space-y-2">
            {(data?.items || [])
              .filter((prompt: any) => !String(prompt.key || "").startsWith("after_photo"))
              .map((prompt: any) => (
                <button
                  key={prompt.id}
                  onClick={() => {
                    setSelected(prompt);
                    setContent(prompt.content);
                  }}
                  className={`w-full rounded-card border p-3 text-left ${selected?.id === prompt.id ? "border-rose bg-pearl/70" : "border-pearl hover:bg-milk"}`}
                >
                  <p className="font-semibold">{prompt.name}</p>
                  <p className="text-xs text-clay">{prompt.key}</p>
                </button>
              ))}
          </div>
        </Card>
        <Card>
          <h2 className="mb-3 font-bold">{selected?.name || "Prompt"}</h2>
          <div className="mb-3 flex flex-wrap gap-2 text-xs text-clay">
            {(selected?.variables || []).map((variable: string) => <span key={variable} className="rounded-full bg-pearl px-2 py-1">{`{{${variable}}}`}</span>)}
          </div>
          <Textarea value={content} onChange={(event) => setContent(event.target.value)} className="min-h-[560px] font-mono text-xs" />
          <Button className="mt-4" onClick={() => mutation.mutate()} disabled={!selected}>Сохранить prompt</Button>
        </Card>
      </div>
    </div>
  );
}

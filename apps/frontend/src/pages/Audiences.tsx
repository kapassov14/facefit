import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Database, Save, Trash2, Users } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";

import { apiRequest } from "../api/client";
import { Button, Card, Input, SectionTitle, Textarea } from "../components/ui";
import { formatDate } from "./crmShared";

type Audience = {
  id: number;
  name: string;
  description?: string | null;
  color: string;
  clients_count: number;
  created_at?: string;
};

export function Audiences() {
  const qc = useQueryClient();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [color, setColor] = useState("#be7d86");
  const [editing, setEditing] = useState<Record<number, Audience>>({});
  const { data } = useQuery<{ items: Audience[] }>({ queryKey: ["audiences"], queryFn: () => apiRequest("/api/admin/audiences") });
  const create = useMutation({
    mutationFn: () => apiRequest("/api/admin/audiences", { method: "POST", body: JSON.stringify({ name, description, color }) }),
    onSuccess: () => {
      setName("");
      setDescription("");
      setColor("#be7d86");
      qc.invalidateQueries({ queryKey: ["audiences"] });
      qc.invalidateQueries({ queryKey: ["crm-options"] });
    }
  });
  const patch = useMutation({
    mutationFn: (audience: Audience) =>
      apiRequest(`/api/admin/audiences/${audience.id}`, {
        method: "PATCH",
        body: JSON.stringify({ name: audience.name, description: audience.description, color: audience.color })
      }),
    onSuccess: () => {
      setEditing({});
      qc.invalidateQueries({ queryKey: ["audiences"] });
      qc.invalidateQueries({ queryKey: ["crm-options"] });
    }
  });
  const remove = useMutation({
    mutationFn: (id: number) => apiRequest(`/api/admin/audiences/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["audiences"] });
      qc.invalidateQueries({ queryKey: ["crm-options"] });
    }
  });
  const items = data?.items || [];
  const totalClients = items.reduce((sum, item) => sum + item.clients_count, 0);
  const setEdit = (id: number, patchValue: Partial<Audience>) => setEditing((current) => ({ ...current, [id]: { ...(current[id] || items.find((item) => item.id === id)!), ...patchValue } }));
  return (
    <div>
      <SectionTitle title="Базы клиентов" subtitle="Сегменты для CRM, рассылок и аналитики" />
      <div className="mb-5 grid gap-3 md:grid-cols-3">
        <Card className="p-4">
          <p className="text-xs font-semibold text-clay">Всего баз</p>
          <p className="mt-2 text-2xl font-bold">{items.length}</p>
        </Card>
        <Card className="p-4">
          <p className="text-xs font-semibold text-clay">Клиентов в базах</p>
          <p className="mt-2 text-2xl font-bold">{totalClients}</p>
        </Card>
        <Card className="p-4">
          <p className="text-xs font-semibold text-clay">Самая большая база</p>
          <p className="mt-2 text-xl font-bold">{items.slice().sort((a, b) => b.clients_count - a.clients_count)[0]?.name || "—"}</p>
        </Card>
      </div>
      <Card className="mb-5">
        <div className="mb-4 flex items-center gap-2 font-bold">
          <Database size={18} />
          Новая база
        </div>
        <div className="grid gap-3 md:grid-cols-[1fr_120px_auto]">
          <Input value={name} onChange={(event) => setName(event.target.value)} placeholder="Название базы" />
          <Input type="color" value={color} onChange={(event) => setColor(event.target.value)} />
          <Button type="button" onClick={() => create.mutate()} disabled={!name.trim()}>Создать</Button>
        </div>
        <Textarea className="mt-3 min-h-20" value={description} onChange={(event) => setDescription(event.target.value)} placeholder="Описание" />
      </Card>
      <div className="grid gap-4 lg:grid-cols-2">
        {items.map((item) => {
          const draft = editing[item.id] || item;
          const isEditing = Boolean(editing[item.id]);
          return (
            <Card key={item.id}>
              <div className="flex items-start justify-between gap-3">
                <div className="flex items-start gap-3">
                  <span className="mt-1 h-4 w-4 rounded-full" style={{ backgroundColor: draft.color }} />
                  <div>
                    {isEditing ? (
                      <Input value={draft.name} onChange={(event) => setEdit(item.id, { name: event.target.value })} />
                    ) : (
                      <h2 className="font-bold">{item.name}</h2>
                    )}
                    <p className="mt-1 text-xs text-clay">Создана {formatDate(item.created_at)}</p>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <Link to={`/admin/crm?audience_id=${item.id}`} className="inline-flex h-9 items-center gap-2 rounded-card bg-pearl px-3 text-sm font-semibold text-ink hover:bg-[#ead9cf]">
                    <Users size={15} />
                    {item.clients_count}
                  </Link>
                  {isEditing ? (
                    <Button className="h-9 px-3" type="button" onClick={() => patch.mutate(draft)}>
                      <Save size={15} />
                    </Button>
                  ) : (
                    <Button className="h-9 px-3" variant="secondary" type="button" onClick={() => setEditing((current) => ({ ...current, [item.id]: item }))}>
                      Изменить
                    </Button>
                  )}
                  <Button className="h-9 px-3" variant="danger" type="button" onClick={() => remove.mutate(item.id)} disabled={item.clients_count > 0}>
                    <Trash2 size={15} />
                  </Button>
                </div>
              </div>
              {isEditing ? (
                <div className="mt-3 grid gap-3 md:grid-cols-[1fr_96px]">
                  <Textarea className="min-h-20" value={draft.description || ""} onChange={(event) => setEdit(item.id, { description: event.target.value })} />
                  <Input type="color" value={draft.color} onChange={(event) => setEdit(item.id, { color: event.target.value })} />
                </div>
              ) : (
                <p className="mt-4 text-sm text-clay">{item.description || "Без описания"}</p>
              )}
            </Card>
          );
        })}
      </div>
    </div>
  );
}

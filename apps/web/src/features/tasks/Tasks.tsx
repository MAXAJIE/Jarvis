import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api, type Task } from "../../lib/api";

export default function Tasks() {
  const queryClient = useQueryClient();
  const [title, setTitle] = useState("");

  const tasks = useQuery({
    queryKey: ["tasks"],
    queryFn: () => api<Task[]>("/api/tasks"),
  });

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ["tasks"] });
    void queryClient.invalidateQueries({ queryKey: ["dashboard"] });
  };

  const create = useMutation({
    mutationFn: (value: string) =>
      api<Task>("/api/tasks", { method: "POST", body: JSON.stringify({ title: value }) }),
    onSuccess: () => {
      setTitle("");
      invalidate();
    },
  });

  const patch = useMutation({
    mutationFn: ({ id, status }: { id: string; status: string }) =>
      api<Task>(`/api/tasks/${id}`, { method: "PATCH", body: JSON.stringify({ status }) }),
    onSuccess: invalidate,
  });

  const remove = useMutation({
    mutationFn: (id: string) => api<{ deleted: boolean }>(`/api/tasks/${id}`, { method: "DELETE" }),
    onSuccess: invalidate,
  });

  return (
    <div className="card space-y-4 p-4">
      <form
        className="flex gap-2"
        onSubmit={(event) => {
          event.preventDefault();
          if (title.trim()) create.mutate(title.trim());
        }}
      >
        <input
          className="field"
          placeholder="new task"
          value={title}
          onChange={(event) => setTitle(event.target.value)}
        />
        <button className="btn btn-primary" type="submit" disabled={create.isPending}>
          Add
        </button>
      </form>

      {tasks.isLoading ? <p className="text-sm text-slate-400">loading…</p> : null}
      {tasks.data?.length === 0 ? (
        <p className="text-sm text-slate-500">No tasks yet.</p>
      ) : null}

      <ul className="divide-y divide-[var(--color-line)]">
        {tasks.data?.map((task) => (
          <li key={task.id} className="flex flex-wrap items-center gap-2 py-2">
            <span className="min-w-0 flex-1 truncate text-sm">{task.title}</span>
            <span className="text-xs text-slate-500">{task.status}</span>
            {task.due_at ? (
              <span className="text-xs text-slate-500">{task.due_at.slice(0, 10)}</span>
            ) : null}
            <button
              className="btn"
              type="button"
              disabled={task.status === "done"}
              onClick={() => patch.mutate({ id: task.id, status: "done" })}
            >
              Done
            </button>
            <button className="btn btn-danger" type="button" onClick={() => remove.mutate(task.id)}>
              Delete
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

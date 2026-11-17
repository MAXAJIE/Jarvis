import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api, type Task } from "../../lib/api";

export default function Tasks({ query }: { query: string }) {
  const queryClient = useQueryClient();
  const [title, setTitle] = useState("");

  const tasks = useQuery({
    queryKey: ["tasks"],
    queryFn: () => api<Task[]>("/api/tasks"),
  });

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ["tasks"] });
    void queryClient.invalidateQueries({ queryKey: ["overview"] });
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

  const needle = query.trim().toLowerCase();
  const rows = (tasks.data ?? []).filter(
    (task) => !needle || task.title.toLowerCase().includes(needle),
  );
  const open = rows.filter((task) => task.status !== "done").length;
  const done = rows.length - open;

  return (
    <div className="panel flex min-h-0 flex-1 flex-col">
      <div className="panel-head">
        <span className="flex-1">Task Ledger</span>
        <span>
          {open} open · {done} done
        </span>
      </div>

      <form
        className="flex shrink-0 gap-2 border-b border-[var(--color-line)] p-2.5"
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

      <div className="min-h-0 flex-1 overflow-y-auto p-2.5">
        {tasks.isLoading ? (
          <p className="text-[0.72rem] text-[var(--color-mute)]">loading…</p>
        ) : null}
        {!tasks.isLoading && rows.length === 0 ? (
          <p className="text-[0.72rem] text-[var(--color-mute)]">
            {needle ? "Nothing matches that search." : "No tasks yet."}
          </p>
        ) : null}
        <ul className="space-y-1">
          {rows.map((task) => (
            <li
              key={task.id}
              className="flex flex-wrap items-center gap-2 rounded border border-[var(--color-line)] bg-[rgba(8,25,40,0.55)] px-2 py-1.5"
            >
              <span className="min-w-0 flex-1 truncate text-[0.76rem]" title={task.title}>
                {task.title}
              </span>
              <span
                className={`tag ${
                  task.status === "done" ? "tag-ok" : "bg-cyan-500/10 text-cyan-200"
                }`}
              >
                {task.status}
              </span>
              {task.due_at ? (
                <span className="kpi text-[0.62rem] text-[var(--color-mute)]">
                  {task.due_at.slice(0, 10)}
                </span>
              ) : null}
              <span className="text-[0.62rem] text-[var(--color-mute)]">P{task.priority}</span>
              <button
                className="btn !px-2 !py-0.5 !text-[0.66rem]"
                type="button"
                disabled={task.status === "done"}
                onClick={() => patch.mutate({ id: task.id, status: "done" })}
              >
                Done
              </button>
              <button
                className="btn btn-danger !px-2 !py-0.5 !text-[0.66rem]"
                type="button"
                onClick={() => remove.mutate(task.id)}
              >
                Delete
              </button>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

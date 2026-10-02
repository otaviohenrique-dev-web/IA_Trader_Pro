"use client";

import React, { useState } from "react";
import { Brain, Database, Key, Upload, ChevronDown } from "lucide-react";
import { backendHttpBase } from "../lib/api";

export default function AdminPanel({ model }) {
  const [senha, setSenha] = useState("");
  const [files, setFiles] = useState([]);
  const [loading, setLoading] = useState(false);
  const [msg, setMsg] = useState("");
  const API = backendHttpBase();

  const download = async () => {
    if (!senha) return setMsg("Digite a senha de administrador.");
    setMsg("Gerando arquivo…");
    try {
      const res = await fetch(`${API}/api/download-dados`, { headers: { "x-admin-password": senha } });
      if (!res.ok) throw new Error(res.status === 401 ? "senha incorreta" : "sem dados ainda");
      const url = URL.createObjectURL(await res.blob());
      const a = Object.assign(document.createElement("a"), { href: url, download: `historico_bot_${Date.now()}.csv` });
      document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url);
      setMsg("Download concluído.");
    } catch (e) { setMsg(`Erro: ${e.message}`); }
  };

  const resume = async () => {
    if (!senha) return setMsg("Digite a senha de administrador.");
    try {
      const res = await fetch(`${API}/api/resume`, { method: "POST", headers: { "x-admin-password": senha } });
      setMsg(res.ok ? "Robô reativado." : res.status === 401 ? "Erro: senha incorreta" : `Erro: HTTP ${res.status}`);
    } catch (e) { setMsg(`Erro: ${e.message}`); }
  };

  const testAlert = async () => {
    if (!senha) return setMsg("Digite a senha de administrador.");
    setMsg("Enviando teste ao Telegram…");
    try {
      const res = await fetch(`${API}/api/test-alert`, { method: "POST", headers: { "x-admin-password": senha } });
      if (res.status === 401) return setMsg("Erro: senha incorreta");
      const d = await res.json();
      setMsg(d.enviado ? "Alerta enviado: confira o Telegram." : `Não enviou: ${d.detalhe}`);
    } catch (e) { setMsg(`Erro: ${e.message}`); }
  };

  const upload = async () => {
    if (!senha || !files.length) return setMsg("Informe a senha e escolha os arquivos.");
    setLoading(true);
    // as estatísticas precisam chegar antes do modelo, que só entra em uso se as encontrar
    const ordered = [...files].sort((a, b) => Number(b.name.endsWith(".json")) - Number(a.name.endsWith(".json")));
    try {
      for (const f of ordered) {
        setMsg(`Enviando ${f.name}…`);
        const body = new FormData();
        body.append("file", f);
        const res = await fetch(`${API}/api/upload-cerebro`, { method: "POST", headers: { "x-admin-password": senha }, body });
        if (!res.ok) {
          const detail = (await res.json().catch(() => ({}))).detail;
          throw new Error(res.status === 401 ? "senha incorreta" : detail || `HTTP ${res.status}`);
        }
      }
      setMsg("Cérebro aplicado com sucesso.");
      setFiles([]);
    } catch (e) { setMsg(`Erro: ${e.message}`); }
    setLoading(false);
  };

  const field = "w-full rounded-lg border border-line bg-black/30 px-3 py-2 text-sm text-slate-200 outline-none focus:border-accent/50";

  return (
    <details className="card group overflow-hidden">
      <summary className="flex cursor-pointer list-none items-center justify-between px-5 py-4">
        <span className="flex items-center gap-2 text-sm font-bold text-white">
          <Brain size={16} className="text-violet" /> Laboratório neural
          <span className="text-[10px] font-medium text-slate-500">· área administrativa</span>
        </span>
        <ChevronDown size={16} className="text-slate-500 transition-transform group-open:rotate-180" />
      </summary>

      <div className="grid gap-4 border-t border-line p-5 md:grid-cols-3">
        <div className="space-y-2">
          <label className="eyebrow flex items-center gap-1.5"><Key size={12} /> Senha</label>
          <input type="password" value={senha} onChange={(e) => setSenha(e.target.value)} placeholder="••••••••" className={field} />
          {msg && <p className="rounded-lg border border-violet/20 bg-violet/10 px-2.5 py-1.5 text-[11px] text-violet">{msg}</p>}
        </div>

        <div className="flex flex-col justify-between gap-2">
          <label className="eyebrow flex items-center gap-1.5"><Database size={12} /> Histórico de operações</label>
          <button type="button" onClick={download}
            className="rounded-lg border border-accent/40 bg-accent/10 py-2 text-xs font-bold text-accent transition-colors hover:bg-accent/20">
            Exportar CSV
          </button>
          <button type="button" onClick={resume}
            className="rounded-lg border border-warn/40 bg-warn/10 py-2 text-xs font-bold text-warn transition-colors hover:bg-warn/20">
            Reativar robô (após kill-switch)
          </button>
          <button type="button" onClick={testAlert}
            className="rounded-lg border border-line bg-white/5 py-2 text-xs font-bold text-slate-300 transition-colors hover:bg-white/10">
            Testar alerta do Telegram
          </button>
        </div>

        <div className="flex flex-col gap-2">
          <label className="eyebrow flex items-center gap-1.5"><Upload size={12} /> Injetar cérebro</label>
          <span className="text-[10px] text-slate-500">Atual: {model?.name || "nenhum"} · envie o .onnx e o .stats.json juntos</span>
          <input type="file" multiple accept=".onnx,.json" onChange={(e) => setFiles(Array.from(e.target.files || []))}
            className="text-[11px] text-slate-400 file:mr-2 file:rounded-md file:border-0 file:bg-white/10 file:px-2 file:py-1 file:text-slate-200" />
          <button type="button" onClick={upload} disabled={loading || !files.length}
            className="rounded-lg bg-violet/80 py-2 text-xs font-bold text-white transition-colors hover:bg-violet disabled:opacity-40">
            {loading ? "Enviando…" : "Aplicar cérebro"}
          </button>
        </div>
      </div>
    </details>
  );
}

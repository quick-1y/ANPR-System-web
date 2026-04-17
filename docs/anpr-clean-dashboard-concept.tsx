// Visual/layout reference for the ANPR UI redesign.
// This file is not meant to be mounted in production as-is.
// It defines the target layout language, spacing, hierarchy, and panel composition.

import React, { useMemo, useState } from "react";
import { motion } from "framer-motion";
import {
  Activity,
  AlertTriangle,
  ArrowDownToLine,
  ArrowUpFromLine,
  Bug,
  Cable,
  Car,
  ChevronDown,
  Clock3,
  Cpu,
  Database,
  Gauge,
  LayoutGrid,
  ListChecks,
  LogOut,
  Map,
  Minus,
  Moon,
  Plus,
  Search,
  Server,
  Settings,
  Shield,
  SlidersHorizontal,
  SunMedium,
  Table2,
  Upload,
  UserPlus,
  Users,
  Video,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

const tabs = [
  { id: "obs", label: "Наблюдение", icon: Video },
  { id: "journal", label: "Журнал", icon: Table2 },
  { id: "zones", label: "Зоны", icon: Map },
  { id: "clients", label: "Клиенты", icon: Users },
  { id: "settings", label: "Настройки", icon: Settings },
];

const channels = [
  { id: 1, name: "Канал 1", zone: "Север", channelType: "Въезд", status: "online", fps: 12, plate: "A123BC 777", rtsp: "rtsp://cam-1/stream" },
  { id: 2, name: "Канал 2", zone: "Склад", channelType: "Въезд", status: "online", fps: 9, plate: "T002OP 750", rtsp: "rtsp://cam-2/stream" },
  { id: 3, name: "Канал 3", zone: "Гость", channelType: "Выезд", status: "online", fps: 11, plate: "M458KT 799", rtsp: "rtsp://cam-3/stream" },
  { id: 4, name: "Канал 4", zone: "Север", channelType: "Въезд", status: "warning", fps: 7, plate: "X773AA 199", rtsp: "rtsp://cam-4/stream" },
  { id: 5, name: "Канал 5", zone: "Периметр", channelType: "Въезд", status: "offline", fps: 0, plate: "—", rtsp: "rtsp://cam-5/stream" },
  { id: 6, name: "Канал 6", zone: "Склад", channelType: "Выезд", status: "online", fps: 10, plate: "K111KK 777", rtsp: "rtsp://cam-6/stream" },
];

const events = [
  { id: 1, plate: "A123BC 777", channel: "Канал 1", zone: "Север", time: "14:02:18", type: "match", direction: "Въезд", confidence: "98%", entry: "14:02:18", exit: "—" },
  { id: 2, plate: "M458KT 799", channel: "Канал 3", zone: "Гость", time: "14:01:44", type: "normal", direction: "Выезд", confidence: "96%", entry: "11:32:15", exit: "14:01:44" },
  { id: 3, plate: "T002OP 750", channel: "Канал 2", zone: "Склад", time: "13:59:51", type: "alert", direction: "Въезд", confidence: "91%", entry: "13:59:51", exit: "—" },
  { id: 4, plate: "X773AA 199", channel: "Канал 4", zone: "Север", time: "13:58:06", type: "normal", direction: "Въезд", confidence: "89%", entry: "13:58:06", exit: "—" },
];

const zones = [
  { id: 1, name: "Север", capacity: 100, occupied: 64, channels: [1, 4], status: "Активна" },
  { id: 2, name: "Гость", capacity: 32, occupied: 17, channels: [3], status: "Активна" },
  { id: 3, name: "Склад", capacity: 40, occupied: 40, channels: [2, 6], status: "Заполнена" },
];

const lists = [
  { id: 1, name: "VIP", type: "Белый список", entries: 14 },
  { id: 2, name: "Служебные", type: "Информационный список", entries: 38 },
  { id: 3, name: "Черный список", type: "Черный список", entries: 5 },
  { id: 4, name: "Гости", type: "Белый список", entries: 64 },
];

const clients = [
  { id: 1, plate: "A123BC 777", lastName: "Иванов", firstName: "Павел", phone: "+49 176 000 00 00", car: "Toyota Camry", comment: "Служебный транспорт", lists: ["VIP", "Служебные"] },
  { id: 2, plate: "M458KT 799", lastName: "Smirnov", firstName: "Alex", phone: "+49 176 111 11 11", car: "BMW 5", comment: "Гостевой пропуск", lists: ["Гости"] },
  { id: 3, plate: "X773AA 199", lastName: "Petrov", firstName: "Ilya", phone: "+49 176 222 22 22", car: "Audi A6", comment: "Проверять вручную", lists: ["Черный список"] },
];

const listMembersMap = {
  1: [clients[0]],
  2: [clients[0]],
  3: [clients[2]],
  4: [clients[1]],
};

const controllers = [
  { id: 1, name: "Шлагбаум север", type: "DTWONDER2CH", address: "192.168.1.61", relay1Mode: "Импульс", relay2Mode: "Импульс с таймером", relay1Delay: 1, relay2Delay: 3, relay1Hotkey: "F9", relay2Hotkey: "F10" },
  { id: 2, name: "Склад ворота", type: "DTWONDER2CH", address: "192.168.1.62", relay1Mode: "Импульс", relay2Mode: "Импульс", relay1Delay: 1, relay2Delay: 1, relay1Hotkey: "F7", relay2Hotkey: "F8" },
];

const users = [
  { id: 1, login: "operator_1", role: "operator", active: true, tabs: ["Наблюдение", "Журнал", "Клиенты"] },
  { id: 2, login: "admin_1", role: "admin", active: true, tabs: ["Наблюдение", "Журнал", "Зоны", "Клиенты", "Настройки"] },
  { id: 3, login: "superadmin", role: "superadmin", active: true, tabs: ["Все вкладки"] },
];

const generalSections = [
  {
    title: "Интерфейс",
    rows: [
      { label: "Сетка превью", value: "2×2", type: "select" },
      { label: "Тема оформления", value: "Светлая", type: "select" },
      { label: "Зафиксировать левую панель", value: true, type: "toggle" },
    ],
  },
  {
    title: "Переподключение",
    rows: [
      { label: "Контроль потери сигнала", value: true, type: "toggle" },
      { label: "Таймаут кадра (сек)", value: "15", type: "input" },
      { label: "Интервал повтора (сек)", value: "10", type: "input" },
      { label: "Периодическое переподключение", value: false, type: "toggle" },
      { label: "Период (мин)", value: "30", type: "input" },
    ],
  },
  {
    title: "Скриншоты и медиа",
    rows: [
      { label: "Лимит хранения (МБ)", value: "2048", type: "input" },
      { label: "Хранить медиа (дней)", value: "14", type: "input" },
    ],
  },
  {
    title: "Логи",
    rows: [
      { label: "Уровень логирования", value: "INFO", type: "select" },
      { label: "Хранить логи (дней)", value: "30", type: "input" },
    ],
  },
  {
    title: "Автоочистка данных",
    rows: [
      { label: "Автоматическая очистка", value: true, type: "toggle" },
      { label: "Интервал проверки (мин)", value: "60", type: "input" },
      { label: "Хранить события (дней)", value: "30", type: "input" },
    ],
  },
  {
    title: "Отображение времени",
    rows: [
      { label: "Часовой пояс", value: "UTC+03:00", type: "select" },
      { label: "Дополнительное смещение (мин)", value: "0", type: "input" },
    ],
  },
  {
    title: "Распознавание номеров",
    rows: [
      { label: "Страны", value: "RU, DE, KZ", type: "input" },
    ],
  },
];

function cn(...classes) {
  return classes.filter(Boolean).join(" ");
}

function surface(theme, dark, light) {
  return theme === "dark" ? dark : light;
}

function textPrimary(theme) {
  return theme === "dark" ? "text-slate-100" : "text-slate-900";
}

function textSecondary(theme) {
  return theme === "dark" ? "text-slate-400" : "text-slate-500";
}

function textMuted(theme) {
  return theme === "dark" ? "text-slate-300" : "text-slate-600";
}

function panelClass(theme) {
  return cn(
    "rounded-[22px] border shadow-sm",
    surface(theme, "border-white/10 bg-slate-900", "border-slate-200 bg-white")
  );
}

function softBlockClass(theme) {
  return cn(
    "rounded-2xl border",
    surface(theme, "border-white/10 bg-white/[0.04]", "border-slate-200 bg-slate-50")
  );
}

function neutralBadgeClass(theme) {
  return surface(theme, "border-white/10 bg-white/[0.06] text-slate-200", "border-slate-200 bg-white text-slate-700");
}

function accentBadgeClass(theme) {
  return surface(theme, "border-blue-400/20 bg-blue-500/10 text-blue-200", "border-blue-200 bg-blue-50 text-blue-700");
}

function warningBadgeClass(theme) {
  return surface(theme, "border-amber-400/20 bg-amber-500/10 text-amber-200", "border-amber-200 bg-amber-50 text-amber-700");
}

function dangerBadgeClass(theme) {
  return surface(theme, "border-rose-400/20 bg-rose-500/10 text-rose-200", "border-rose-200 bg-rose-50 text-rose-700");
}

function successBadgeClass(theme) {
  return surface(theme, "border-emerald-400/20 bg-emerald-500/10 text-emerald-200", "border-emerald-200 bg-emerald-50 text-emerald-700");
}

function MinimalBadge({ children, className = "" }) {
  return <span className={cn("inline-flex items-center rounded-xl border px-2.5 py-1 text-xs font-medium", className)}>{children}</span>;
}

function SectionEyebrow({ children, theme }) {
  return <div className={cn("mb-1 text-[11px] font-medium uppercase tracking-[0.12em]", textSecondary(theme))}>{children}</div>;
}

function MetricPill({ icon: Icon, label, value, theme }) {
  return (
    <div className={cn("flex items-center gap-3 rounded-2xl border px-3 py-2.5", surface(theme, "border-white/10 bg-white/[0.04]", "border-slate-200 bg-white"))}>
      <div className={cn("flex h-9 w-9 items-center justify-center rounded-xl", surface(theme, "bg-blue-500/12 text-blue-200", "bg-blue-50 text-blue-700"))}>
        <Icon className="h-4 w-4" />
      </div>
      <div>
        <div className={cn("text-[11px] uppercase tracking-[0.12em]", textSecondary(theme))}>{label}</div>
        <div className={cn("text-sm font-semibold", textPrimary(theme))}>{value}</div>
      </div>
    </div>
  );
}

function AppFrame({ children, theme }) {
  return (
    <div className={cn("min-h-screen w-full p-3 md:p-5", theme === "dark" ? "bg-slate-950 text-slate-100" : "bg-slate-100 text-slate-900")}>
      <div className={cn("mx-auto flex min-h-[90vh] max-w-[1600px] overflow-hidden rounded-[28px] border shadow-2xl", surface(theme, "border-white/10 bg-slate-900", "border-slate-200 bg-slate-50"))}>
        {children}
      </div>
    </div>
  );
}

function Modal({ open, onClose, title, theme, children, footer }) {
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/45 p-4 backdrop-blur-sm">
      <div className={cn("w-full max-w-[520px] rounded-[24px] border shadow-2xl", surface(theme, "border-white/10 bg-slate-900", "border-slate-200 bg-white"))}>
        <div className={cn("flex items-center justify-between border-b px-5 py-4", surface(theme, "border-white/10", "border-slate-200"))}>
          <div className={cn("text-base font-semibold", textPrimary(theme))}>{title}</div>
          <Button variant="ghost" className="h-9 rounded-xl px-3" onClick={onClose}>✕</Button>
        </div>
        <div className="space-y-4 px-5 py-4">{children}</div>
        <div className={cn("flex justify-end gap-2 border-t px-5 py-4", surface(theme, "border-white/10", "border-slate-200"))}>{footer}</div>
      </div>
    </div>
  );
}

function SidebarListItem({ active, title, subtitle, right, onClick, theme }) {
  return (
    <button
      onClick={onClick}
      className={cn(
        "w-full rounded-2xl border px-3 py-3 text-left transition",
        active
          ? surface(theme, "border-blue-400/20 bg-blue-500/10", "border-blue-200 bg-blue-50")
          : surface(theme, "border-white/10 bg-white/[0.03] hover:bg-white/[0.05]", "border-slate-200 bg-white hover:bg-slate-50")
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className={cn("text-sm font-semibold", textPrimary(theme))}>{title}</div>
          {subtitle ? <div className={cn("mt-1 text-xs", textSecondary(theme))}>{subtitle}</div> : null}
        </div>
        {right}
      </div>
    </button>
  );
}

function Field({ label, value, theme, help = true, wide = false }) {
  return (
    <div className={cn("grid gap-3 md:items-center", wide ? "md:grid-cols-1" : "md:grid-cols-[220px_minmax(0,1fr)]")}>
      <div className="flex items-center gap-2">
        {help ? <span className={cn("inline-flex h-5 w-5 items-center justify-center rounded-full border text-[11px]", neutralBadgeClass(theme))}>?</span> : null}
        <div className={cn("text-sm font-medium", textPrimary(theme))}>{label}</div>
      </div>
      <Input className="max-w-[320px] rounded-2xl" value={value} readOnly />
    </div>
  );
}

function SelectField({ label, value, theme, help = true }) {
  return (
    <div className="grid gap-3 md:grid-cols-[220px_minmax(0,1fr)] md:items-center">
      <div className="flex items-center gap-2">
        {help ? <span className={cn("inline-flex h-5 w-5 items-center justify-center rounded-full border text-[11px]", neutralBadgeClass(theme))}>?</span> : null}
        <div className={cn("text-sm font-medium", textPrimary(theme))}>{label}</div>
      </div>
      <button className={cn("flex max-w-[320px] items-center justify-between rounded-2xl border px-3 py-2 text-sm", surface(theme, "border-white/10 bg-white/[0.04] text-slate-200", "border-slate-200 bg-white text-slate-700"))}>
        <span>{value}</span>
        <ChevronDown className="h-4 w-4" />
      </button>
    </div>
  );
}

function ToggleField({ label, checked, theme, help = true }) {
  return (
    <div className="grid gap-3 md:grid-cols-[220px_minmax(0,1fr)] md:items-center">
      <div className="flex items-center gap-2">
        {help ? <span className={cn("inline-flex h-5 w-5 items-center justify-center rounded-full border text-[11px]", neutralBadgeClass(theme))}>?</span> : null}
        <div className={cn("text-sm font-medium", textPrimary(theme))}>{label}</div>
      </div>
      <div>
        <button className={cn("relative h-7 w-12 rounded-full border transition", checked ? surface(theme, "border-blue-400/20 bg-blue-500/20", "border-blue-200 bg-blue-100") : surface(theme, "border-white/10 bg-white/[0.04]", "border-slate-200 bg-slate-100"))}>
          <span className={cn("absolute top-1 h-5 w-5 rounded-full bg-white shadow transition", checked ? "left-6" : "left-1")} />
        </button>
      </div>
    </div>
  );
}

function Rail({ activeTab, setActiveTab, theme, role }) {
  return (
    <>
      <aside className={cn("hidden w-[88px] shrink-0 border-r px-3 py-4 lg:flex lg:flex-col", surface(theme, "border-white/10 bg-slate-950/80", "border-slate-200 bg-white"))}>
        <div className="mb-4 flex items-center justify-center">
          <div className={cn("flex h-11 w-11 items-center justify-center rounded-2xl", surface(theme, "bg-blue-500/12 text-blue-200", "bg-blue-50 text-blue-700"))}>
            <Car className="h-5 w-5" />
          </div>
        </div>

        <nav className="flex flex-1 flex-col gap-2">
          {tabs.map((tab) => {
            const Icon = tab.icon;
            const active = activeTab === tab.id;
            return (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={cn(
                  "group flex flex-col items-center gap-2 rounded-2xl border px-2 py-3 text-center transition",
                  active
                    ? surface(theme, "border-blue-400/20 bg-blue-500/10 text-blue-200", "border-blue-200 bg-blue-50 text-blue-700")
                    : surface(theme, "border-transparent text-slate-400 hover:border-white/10 hover:bg-white/[0.04] hover:text-slate-100", "border-transparent text-slate-500 hover:border-slate-200 hover:bg-slate-100 hover:text-slate-900")
                )}
              >
                <Icon className="h-5 w-5" />
                <span className="text-[11px] font-medium leading-tight">{tab.label}</span>
              </button>
            );
          })}
        </nav>

        <button className={cn("mt-4 flex flex-col items-center gap-2 rounded-2xl border px-2 py-3 text-center transition", surface(theme, "border-white/10 text-slate-400 hover:bg-white/[0.04] hover:text-slate-100", "border-slate-200 text-slate-500 hover:bg-slate-100 hover:text-slate-900"))}>
          <LogOut className="h-5 w-5" />
          <span className="text-[11px] font-medium">{role}</span>
        </button>
      </aside>

      <div className={cn("fixed inset-x-3 bottom-3 z-30 rounded-[22px] border p-2 shadow-2xl lg:hidden", surface(theme, "border-white/10 bg-slate-900/95 backdrop-blur", "border-slate-200 bg-white/95 backdrop-blur"))}>
        <div className="grid grid-cols-5 gap-1">
          {tabs.map((tab) => {
            const Icon = tab.icon;
            const active = activeTab === tab.id;
            return (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={cn(
                  "flex flex-col items-center gap-1 rounded-2xl px-2 py-2 text-[10px] font-medium transition",
                  active ? surface(theme, "bg-blue-500/10 text-blue-200", "bg-blue-50 text-blue-700") : surface(theme, "text-slate-400", "text-slate-500")
                )}
              >
                <Icon className="h-4 w-4" />
                <span>{tab.label}</span>
              </button>
            );
          })}
        </div>
      </div>
    </>
  );
}

function ObservationView({ theme, role, selectedEvent, setSelectedEvent }) {
  const [gridSize, setGridSize] = useState("2x2");
  const [expandedChannelId, setExpandedChannelId] = useState(null);
  const [showDebug, setShowDebug] = useState(true);

  const visibleCount = { "1x1": 1, "2x2": 4, "2x3": 6, "3x3": 6 }[gridSize] || 4;
  const visibleChannels = expandedChannelId ? channels.filter((c) => c.id === expandedChannelId) : channels.slice(0, visibleCount);
  const colsClass = expandedChannelId ? "grid-cols-1" : gridSize === "1x1" ? "grid-cols-1" : gridSize === "2x2" ? "grid-cols-1 sm:grid-cols-2" : "grid-cols-1 sm:grid-cols-2 xl:grid-cols-3";

  return (
    <div className="grid h-full gap-4 xl:grid-cols-[minmax(0,1fr)_320px]">
      <div className="grid min-h-[640px] gap-4">
        <Card className={panelClass(theme)}>
          <CardHeader className="flex flex-col gap-3 pb-3 lg:flex-row lg:items-center lg:justify-between">
            <div>
              <SectionEyebrow theme={theme}>Камеры</SectionEyebrow>
              <CardTitle className="text-base">Наблюдение</CardTitle>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <span className={cn("mr-1 text-sm", textSecondary(theme))}>Сетка</span>
              {["1x1", "2x2", "2x3", "3x3"].map((size) => (
                <Button key={size} variant={gridSize === size ? "default" : "outline"} className="rounded-xl" onClick={() => { setExpandedChannelId(null); setGridSize(size); }}>
                  {size.replace("x", "×")}
                </Button>
              ))}
              {role === "superadmin" ? (
                <Button variant="ghost" className="rounded-xl" onClick={() => setShowDebug((v) => !v)}>
                  {showDebug ? "Свернуть логи" : "Логи"}
                </Button>
              ) : null}
            </div>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className={cn("grid gap-3", colsClass)}>
              {visibleChannels.map((channel) => {
                const statusTone = channel.status === "online" ? successBadgeClass(theme) : channel.status === "warning" ? warningBadgeClass(theme) : dangerBadgeClass(theme);
                return (
                  <button
                    key={channel.id}
                    onDoubleClick={() => setExpandedChannelId((v) => (v === channel.id ? null : channel.id))}
                    className={cn("group relative aspect-video overflow-hidden rounded-2xl border text-left", surface(theme, "border-white/10 bg-slate-950", "border-slate-200 bg-slate-100"))}
                  >
                    <div className={cn("absolute inset-0", surface(theme, "bg-gradient-to-br from-slate-800 to-slate-950", "bg-gradient-to-br from-slate-100 to-slate-200"))} />
                    <div className="absolute left-3 top-3 flex flex-wrap items-center gap-2">
                      <MinimalBadge className={accentBadgeClass(theme)}>{channel.name}</MinimalBadge>
                      <MinimalBadge className={statusTone}>{channel.status === "online" ? "Online" : channel.status === "warning" ? "Warning" : "Offline"}</MinimalBadge>
                    </div>
                    <div className={cn("absolute inset-0 flex items-center justify-center opacity-60", theme === "dark" ? "text-slate-500" : "text-slate-400")}>
                      <Video className="h-10 w-10" />
                    </div>
                    <div className="absolute bottom-3 left-3 right-3 flex items-end justify-between gap-3">
                      <div>
                        <div className={cn("text-sm font-semibold", textPrimary(theme))}>{channel.channelType} / {channel.zone}</div>
                        <div className={cn("text-xs", textSecondary(theme))}>{channel.plate} · RTSP · OCR</div>
                      </div>
                      <MinimalBadge className={neutralBadgeClass(theme)}>FPS {channel.fps}</MinimalBadge>
                    </div>
                  </button>
                );
              })}
            </div>

            {role === "superadmin" && showDebug ? (
              <div className={cn("rounded-2xl border", surface(theme, "border-white/10 bg-white/[0.03]", "border-slate-200 bg-slate-50"))}>
                <div className={cn("flex items-center justify-between border-b px-4 py-3", surface(theme, "border-white/10", "border-slate-200"))}>
                  <div className={cn("text-sm font-semibold", textPrimary(theme))}>Логи</div>
                  <Button variant="ghost" className="h-8 rounded-xl px-3" onClick={() => setShowDebug(false)}>Свернуть</Button>
                </div>
                <div className={cn("space-y-2 px-4 py-3 font-mono text-xs", textMuted(theme))}>
                  <div>[14:02:18] channel_runtime: event published → SSE</div>
                  <div>[14:02:19] OCR: bestshot accepted, confidence 0.98</div>
                  <div>[14:02:19] controller: relay 1 not triggered, list filter mismatch</div>
                </div>
              </div>
            ) : null}
          </CardContent>
        </Card>
      </div>

      <Card className={panelClass(theme)}>
        <CardHeader className="pb-3">
          <SectionEyebrow theme={theme}>Поток</SectionEyebrow>
          <CardTitle className="text-base">События</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          {events.map((event, idx) => (
            <motion.button
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: idx * 0.04 }}
              key={event.id}
              onClick={() => setSelectedEvent(event)}
              className={cn(
                "w-full rounded-2xl border p-3 text-left",
                event.type === "match"
                  ? surface(theme, "border-amber-400/20 bg-amber-500/10", "border-amber-200 bg-amber-50")
                  : event.type === "alert"
                  ? surface(theme, "border-rose-400/20 bg-rose-500/10", "border-rose-200 bg-rose-50")
                  : surface(theme, "border-white/10 bg-white/[0.04]", "border-slate-200 bg-slate-50")
              )}
            >
              <div className="mb-2 flex items-start justify-between gap-3">
                <div>
                  <div className={cn("text-sm font-semibold", textPrimary(theme))}>{event.plate}</div>
                  <div className={cn("text-xs", textSecondary(theme))}>{event.channel} · {event.zone} · {event.direction}</div>
                </div>
                <div className={cn("font-mono text-xs", textMuted(theme))}>{event.time}</div>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <MinimalBadge className={neutralBadgeClass(theme)}>RU</MinimalBadge>
                <MinimalBadge className={neutralBadgeClass(theme)}>{event.confidence}</MinimalBadge>
                {event.type === "match" ? <MinimalBadge className={warningBadgeClass(theme)}>Match</MinimalBadge> : null}
                {event.type === "alert" ? <MinimalBadge className={dangerBadgeClass(theme)}>Alert</MinimalBadge> : null}
              </div>
            </motion.button>
          ))}
        </CardContent>
      </Card>
    </div>
  );
}

function JournalView({ theme }) {
  return (
    <div className="space-y-4">
      <Card className={panelClass(theme)}>
        <CardContent className="p-4">
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-6">
            <div className="xl:col-span-2">
              <div className={cn("mb-2 text-xs font-medium", textSecondary(theme))}>Поиск</div>
              <div className="relative">
                <Search className={cn("absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2", theme === "dark" ? "text-slate-500" : "text-slate-400")} />
                <Input className="rounded-2xl pl-9" placeholder="Поиск по номеру..." />
              </div>
            </div>
            <div>
              <div className={cn("mb-2 text-xs font-medium", textSecondary(theme))}>Канал</div>
              <Button variant="outline" className="w-full justify-between rounded-2xl">Все каналы <ChevronDown className="h-4 w-4" /></Button>
            </div>
            <div>
              <div className={cn("mb-2 text-xs font-medium", textSecondary(theme))}>С</div>
              <Input className="rounded-2xl" placeholder="2026-04-17 00:00" />
            </div>
            <div>
              <div className={cn("mb-2 text-xs font-medium", textSecondary(theme))}>По</div>
              <Input className="rounded-2xl" placeholder="2026-04-17 23:59" />
            </div>
            <div className="flex items-end gap-2">
              <Button className="w-full rounded-2xl">Найти</Button>
              <Button variant="outline" className="rounded-2xl">Сброс</Button>
            </div>
          </div>
        </CardContent>
      </Card>

      <Card className={panelClass(theme)}>
        <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
          <div>
            <SectionEyebrow theme={theme}>История</SectionEyebrow>
            <CardTitle className="text-base">Журнал событий</CardTitle>
          </div>
          <Button variant="outline" className="rounded-2xl"><ArrowDownToLine className="mr-2 h-4 w-4" />Экспорт</Button>
        </CardHeader>
        <CardContent className="overflow-x-auto">
          <table className="w-full min-w-[1040px] border-separate border-spacing-0 text-sm">
            <thead>
              <tr className={cn(textSecondary(theme))}>
                {["Время", "Канал", "Страна", "Направление", "Номер", "Увер.", "Источник", "Зона", "Въезд", "Выезд"].map((head) => (
                  <th key={head} className={cn("border-b px-4 py-3 text-left text-[11px] font-semibold uppercase tracking-[0.12em]", surface(theme, "border-white/10", "border-slate-200"))}>{head}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {events.map((row) => (
                <tr key={row.id} className={cn("transition", surface(theme, "hover:bg-white/[0.03]", "hover:bg-slate-50"))}>
                  {[row.time, row.channel, "RU", row.direction, row.plate, row.confidence, "OCR", row.zone, row.entry, row.exit].map((cell, idx) => (
                    <td key={idx} className={cn("border-b px-4 py-3", surface(theme, "border-white/10 text-slate-200", "border-slate-200 text-slate-700"), idx === 4 ? "font-mono font-semibold" : "")}>{cell}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </CardContent>
      </Card>
    </div>
  );
}

function ZonesView({ theme }) {
  const [selectedZoneId, setSelectedZoneId] = useState(1);
  const [showCreateZone, setShowCreateZone] = useState(false);
  const zone = zones.find((z) => z.id === selectedZoneId) || zones[0];

  return (
    <>
      <div className="grid gap-4 xl:grid-cols-[300px_minmax(0,1fr)]">
        <Card className={panelClass(theme)}>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-3">
            <CardTitle className="text-base">Зоны</CardTitle>
            <Button className="rounded-2xl" onClick={() => setShowCreateZone(true)}>+ Создать зону</Button>
          </CardHeader>
          <CardContent className="space-y-3">
            {zones.map((item) => {
              const tone = item.status === "Заполнена" ? warningBadgeClass(theme) : accentBadgeClass(theme);
              return (
                <SidebarListItem
                  key={item.id}
                  active={item.id === selectedZoneId}
                  onClick={() => setSelectedZoneId(item.id)}
                  title={item.name}
                  subtitle={`${item.occupied}/${item.capacity} · ${item.channels.length} канала`}
                  right={<MinimalBadge className={tone}>{item.status}</MinimalBadge>}
                  theme={theme}
                />
              );
            })}
          </CardContent>
        </Card>

        <Card className={panelClass(theme)}>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-3">
            <div>
              <SectionEyebrow theme={theme}>Настройки зоны</SectionEyebrow>
              <CardTitle className="text-base">{zone.name}</CardTitle>
            </div>
            <Button variant="outline" className="rounded-2xl">Закрыть</Button>
          </CardHeader>
          <CardContent className="space-y-5">
            <Field label="Название" value={zone.name} theme={theme} help={false} />
            <Field label="Вместимость" value={String(zone.capacity)} theme={theme} help={false} />
            <div className="grid gap-3 md:grid-cols-[220px_minmax(0,1fr)] md:items-center">
              <div className={cn("text-sm font-medium", textPrimary(theme))}>Занятость</div>
              <div>
                <div className={cn("mb-2 h-2.5 overflow-hidden rounded-full", surface(theme, "bg-white/10", "bg-slate-100"))}>
                  <div className="h-full rounded-full bg-blue-500" style={{ width: `${Math.round((zone.occupied / zone.capacity) * 100)}%` }} />
                </div>
                <div className={cn("text-sm", textSecondary(theme))}>{zone.occupied} из {zone.capacity}</div>
              </div>
            </div>
            <SelectField label="Каналы" value={zone.channels.map((id) => `Канал ${id}`).join(", ")} theme={theme} help={false} />
            <div className="flex gap-2">
              <Button className="rounded-2xl">Сохранить</Button>
              <Button variant="outline" className="rounded-2xl">Удалить зону</Button>
            </div>
          </CardContent>
        </Card>
      </div>

      <Modal
        open={showCreateZone}
        onClose={() => setShowCreateZone(false)}
        title="Создать зону"
        theme={theme}
        footer={
          <>
            <Button variant="ghost" className="rounded-2xl" onClick={() => setShowCreateZone(false)}>Отмена</Button>
            <Button className="rounded-2xl" onClick={() => setShowCreateZone(false)}>Создать</Button>
          </>
        }
      >
        <Field label="Название" value="Новая зона" theme={theme} help={false} />
        <Field label="Вместимость" value="50" theme={theme} help={false} />
      </Modal>
    </>
  );
}

function ClientsView({ theme }) {
  const [clientTab, setClientTab] = useState("clients");
  const [selectedListId, setSelectedListId] = useState(1);
  const [showClientModal, setShowClientModal] = useState(false);
  const [showListModal, setShowListModal] = useState(false);
  const [showAttachModal, setShowAttachModal] = useState(false);

  const selectedList = lists.find((item) => item.id === selectedListId) || lists[0];
  const selectedMembers = listMembersMap[selectedList.id] || [];

  return (
    <>
      <div className="space-y-4">
        <div className="flex flex-wrap gap-2">
          {[
            { id: "clients", label: "Клиенты", icon: Users },
            { id: "lists", label: "Списки", icon: ListChecks },
          ].map((item) => {
            const Icon = item.icon;
            const active = clientTab === item.id;
            return (
              <Button key={item.id} variant={active ? "default" : "outline"} className="rounded-2xl" onClick={() => setClientTab(item.id)}>
                <Icon className="mr-2 h-4 w-4" />
                {item.label}
              </Button>
            );
          })}
        </div>

        {clientTab === "clients" ? (
          <Card className={panelClass(theme)}>
            <CardHeader className="flex flex-col gap-3 pb-2 md:flex-row md:items-center md:justify-between">
              <div>
                <SectionEyebrow theme={theme}>База</SectionEyebrow>
                <CardTitle className="text-base">Клиенты</CardTitle>
              </div>
              <div className="flex flex-wrap gap-2">
                <Button className="rounded-2xl" onClick={() => setShowClientModal(true)}><UserPlus className="mr-2 h-4 w-4" />Добавить клиента</Button>
                <Button variant="outline" className="rounded-2xl">Импорт</Button>
              </div>
            </CardHeader>
            <CardContent className="overflow-x-auto">
              <table className="w-full min-w-[960px] text-sm">
                <thead>
                  <tr className={cn(textSecondary(theme))}>
                    {["Гос. номер", "Фамилия", "Имя", "Телефон", "Марка авто", "Списки"].map((head) => (
                      <th key={head} className={cn("border-b px-4 py-3 text-left text-[11px] font-semibold uppercase tracking-[0.12em]", surface(theme, "border-white/10", "border-slate-200"))}>{head}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {clients.map((row) => (
                    <tr key={row.id} className={cn("transition", surface(theme, "hover:bg-white/[0.03]", "hover:bg-slate-50"))}>
                      <td className={cn("border-b px-4 py-3 font-mono font-semibold", surface(theme, "border-white/10 text-slate-100", "border-slate-200 text-slate-900"))}>{row.plate}</td>
                      <td className={cn("border-b px-4 py-3", surface(theme, "border-white/10 text-slate-200", "border-slate-200 text-slate-700"))}>{row.lastName}</td>
                      <td className={cn("border-b px-4 py-3", surface(theme, "border-white/10 text-slate-200", "border-slate-200 text-slate-700"))}>{row.firstName}</td>
                      <td className={cn("border-b px-4 py-3", surface(theme, "border-white/10 text-slate-200", "border-slate-200 text-slate-700"))}>{row.phone}</td>
                      <td className={cn("border-b px-4 py-3", surface(theme, "border-white/10 text-slate-200", "border-slate-200 text-slate-700"))}>{row.car}</td>
                      <td className={cn("border-b px-4 py-3", surface(theme, "border-white/10", "border-slate-200"))}>
                        <div className="flex flex-wrap gap-2">
                          {row.lists.map((tag) => (
                            <MinimalBadge key={tag} className={neutralBadgeClass(theme)}>{tag}</MinimalBadge>
                          ))}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </CardContent>
          </Card>
        ) : (
          <div className="grid gap-4 xl:grid-cols-[300px_minmax(0,1fr)]">
            <Card className={panelClass(theme)}>
              <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-3">
                <CardTitle className="text-base">Списки номеров</CardTitle>
                <div className="flex gap-2">
                  <Button variant="outline" className="h-9 w-9 rounded-xl p-0" onClick={() => setShowListModal(true)}><Plus className="h-4 w-4" /></Button>
                  <Button variant="outline" className="h-9 w-9 rounded-xl p-0"><Minus className="h-4 w-4" /></Button>
                </div>
              </CardHeader>
              <CardContent className="space-y-3">
                {lists.map((item) => (
                  <SidebarListItem
                    key={item.id}
                    active={item.id === selectedListId}
                    onClick={() => setSelectedListId(item.id)}
                    title={item.name}
                    subtitle={item.type}
                    right={<MinimalBadge className={neutralBadgeClass(theme)}>{item.entries}</MinimalBadge>}
                    theme={theme}
                  />
                ))}
              </CardContent>
            </Card>

            <Card className={panelClass(theme)}>
              <CardHeader className="space-y-3 pb-2">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <SectionEyebrow theme={theme}>Выбранный список</SectionEyebrow>
                    <CardTitle className="text-base">{selectedList.name}</CardTitle>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <Button className="rounded-2xl" onClick={() => setShowAttachModal(true)}>Прикрепить клиента</Button>
                    <Button variant="outline" className="rounded-2xl"><ArrowDownToLine className="mr-2 h-4 w-4" />Экспорт списка</Button>
                    <Button variant="outline" className="rounded-2xl"><ArrowUpFromLine className="mr-2 h-4 w-4" />Импорт списка</Button>
                    <Button variant="outline" className="rounded-2xl">Настройки</Button>
                  </div>
                </div>
                <div className={cn("text-sm", textSecondary(theme))}>{selectedMembers.length ? `${selectedMembers.length} записей` : "Выберите список или создайте новый"}</div>
              </CardHeader>
              <CardContent className="overflow-x-auto">
                <table className="w-full min-w-[940px] text-sm">
                  <thead>
                    <tr className={cn(textSecondary(theme))}>
                      {["Гос. номер", "Фамилия", "Имя", "Телефон", "Марка авто", "Комментарий"].map((head) => (
                        <th key={head} className={cn("border-b px-4 py-3 text-left text-[11px] font-semibold uppercase tracking-[0.12em]", surface(theme, "border-white/10", "border-slate-200"))}>{head}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {selectedMembers.map((row) => (
                      <tr key={row.id} className={cn("transition", surface(theme, "hover:bg-white/[0.03]", "hover:bg-slate-50"))}>
                        <td className={cn("border-b px-4 py-3 font-mono font-semibold", surface(theme, "border-white/10 text-slate-100", "border-slate-200 text-slate-900"))}>{row.plate}</td>
                        <td className={cn("border-b px-4 py-3", surface(theme, "border-white/10 text-slate-200", "border-slate-200 text-slate-700"))}>{row.lastName}</td>
                        <td className={cn("border-b px-4 py-3", surface(theme, "border-white/10 text-slate-200", "border-slate-200 text-slate-700"))}>{row.firstName}</td>
                        <td className={cn("border-b px-4 py-3", surface(theme, "border-white/10 text-slate-200", "border-slate-200 text-slate-700"))}>{row.phone}</td>
                        <td className={cn("border-b px-4 py-3", surface(theme, "border-white/10 text-slate-200", "border-slate-200 text-slate-700"))}>{row.car}</td>
                        <td className={cn("border-b px-4 py-3", surface(theme, "border-white/10 text-slate-200", "border-slate-200 text-slate-700"))}>{row.comment}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </CardContent>
            </Card>
          </div>
        )}
      </div>

      <Modal
        open={showClientModal}
        onClose={() => setShowClientModal(false)}
        title="Клиент"
        theme={theme}
        footer={
          <>
            <Button variant="outline" className="rounded-2xl">Удалить</Button>
            <Button variant="ghost" className="rounded-2xl" onClick={() => setShowClientModal(false)}>Отменить</Button>
            <Button className="rounded-2xl" onClick={() => setShowClientModal(false)}>Сохранить</Button>
          </>
        }
      >
        <Field label="Фамилия" value="Иванов" theme={theme} help={false} />
        <Field label="Имя" value="Павел" theme={theme} help={false} />
        <Field label="Телефон" value="+49 176 000 00 00" theme={theme} help={false} />
        <Field label="Марка автомобиля" value="Toyota Camry" theme={theme} help={false} />
        <Field label="Гос. номер автомобиля" value="A123BC 777" theme={theme} help={false} />
        <SelectField label="Список" value="VIP" theme={theme} help={false} />
      </Modal>

      <Modal
        open={showListModal}
        onClose={() => setShowListModal(false)}
        title="Новый список"
        theme={theme}
        footer={
          <>
            <Button variant="ghost" className="rounded-2xl" onClick={() => setShowListModal(false)}>Отменить</Button>
            <Button className="rounded-2xl" onClick={() => setShowListModal(false)}>Создать</Button>
          </>
        }
      >
        <Field label="Название списка" value="Новый список" theme={theme} help={false} />
        <SelectField label="Тип списка" value="Белый список" theme={theme} help={false} />
      </Modal>

      <Modal
        open={showAttachModal}
        onClose={() => setShowAttachModal(false)}
        title="Прикрепить клиента к списку"
        theme={theme}
        footer={
          <>
            <Button variant="ghost" className="rounded-2xl" onClick={() => setShowAttachModal(false)}>Отменить</Button>
            <Button className="rounded-2xl" onClick={() => setShowAttachModal(false)}>Прикрепить</Button>
          </>
        }
      >
        <SelectField label="Клиент" value="Павел Иванов · A123BC 777" theme={theme} help={false} />
        <SelectField label="Список" value={selectedList.name} theme={theme} help={false} />
      </Modal>
    </>
  );
}

function SettingsView({ theme, role }) {
  const [pane, setPane] = useState("general");
  const [selectedChannelId, setSelectedChannelId] = useState(1);
  const [channelTab, setChannelTab] = useState("channel");
  const [selectedControllerId, setSelectedControllerId] = useState(1);
  const [selectedUserId, setSelectedUserId] = useState(1);

  const channel = channels.find((item) => item.id === selectedChannelId) || channels[0];
  const controller = controllers.find((item) => item.id === selectedControllerId) || controllers[0];
  const user = users.find((item) => item.id === selectedUserId) || users[0];

  const panes = [
    { id: "general", label: "Общие", icon: Settings, visible: true },
    { id: "channels", label: "Каналы", icon: Video, visible: true },
    { id: "controllers", label: "Контроллеры", icon: Cable, visible: true },
    { id: "users", label: "Пользователи", icon: Users, visible: role !== "operator" },
    { id: "sysdata", label: "Системные данные", icon: Database, visible: true },
    { id: "debug", label: "Отладка", icon: Bug, visible: role === "superadmin" },
  ].filter((item) => item.visible);

  return (
    <div className="grid gap-4 xl:grid-cols-[240px_minmax(0,1fr)]">
      <Card className={panelClass(theme)}>
        <CardContent className="p-3">
          <div className="space-y-2">
            <div className={cn("px-3 pt-1 text-[11px] font-medium uppercase tracking-[0.12em]", textSecondary(theme))}>Основное</div>
            {panes.map((item) => {
              const Icon = item.icon;
              const active = pane === item.id;
              return (
                <button
                  key={item.id}
                  onClick={() => setPane(item.id)}
                  className={cn("flex w-full items-center gap-3 rounded-2xl px-3 py-3 text-sm font-medium transition", active ? surface(theme, "bg-blue-500/10 text-blue-200", "bg-blue-50 text-blue-700") : surface(theme, "text-slate-300 hover:bg-white/[0.04]", "text-slate-700 hover:bg-slate-100"))}
                >
                  <Icon className="h-4 w-4" />
                  {item.label}
                </button>
              );
            })}
          </div>
        </CardContent>
      </Card>

      <div className="space-y-4">
        {pane === "general" ? (
          <>
            {generalSections.map((section) => (
              <Card key={section.title} className={panelClass(theme)}>
                <CardHeader className="pb-3">
                  <SectionEyebrow theme={theme}>Раздел</SectionEyebrow>
                  <CardTitle className="text-base">{section.title}</CardTitle>
                </CardHeader>
                <CardContent className="space-y-4">
                  {section.rows.map((row) =>
                    row.type === "toggle" ? (
                      <ToggleField key={row.label} label={row.label} checked={Boolean(row.value)} theme={theme} />
                    ) : row.type === "select" ? (
                      <SelectField key={row.label} label={row.label} value={String(row.value)} theme={theme} />
                    ) : (
                      <Field key={row.label} label={row.label} value={String(row.value)} theme={theme} />
                    )
                  )}
                </CardContent>
              </Card>
            ))}
            <Button className="rounded-2xl">Сохранить настройки</Button>
          </>
        ) : null}

        {pane === "channels" ? (
          <div className="grid gap-4 xl:grid-cols-[280px_minmax(0,1fr)]">
            <Card className={panelClass(theme)}>
              <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-3">
                <CardTitle className="text-base">Каналы</CardTitle>
                <div className="flex gap-2">
                  <Button variant="outline" className="h-9 w-9 rounded-xl p-0"><Plus className="h-4 w-4" /></Button>
                  <Button variant="outline" className="h-9 w-9 rounded-xl p-0"><Minus className="h-4 w-4" /></Button>
                </div>
              </CardHeader>
              <CardContent className="space-y-3">
                {channels.map((item) => (
                  <SidebarListItem
                    key={item.id}
                    active={item.id === selectedChannelId}
                    onClick={() => setSelectedChannelId(item.id)}
                    title={item.name}
                    subtitle={`${item.channelType} · ${item.zone}`}
                    right={<MinimalBadge className={item.status === "online" ? successBadgeClass(theme) : item.status === "warning" ? warningBadgeClass(theme) : dangerBadgeClass(theme)}>{item.status}</MinimalBadge>}
                    theme={theme}
                  />
                ))}
              </CardContent>
            </Card>

            <Card className={panelClass(theme)}>
              <CardHeader className="space-y-3 pb-2">
                <div>
                  <SectionEyebrow theme={theme}>Параметры канала</SectionEyebrow>
                  <CardTitle className="text-base">{channel.name}</CardTitle>
                </div>
                <div className="flex flex-wrap gap-2">
                  {[
                    ["channel", "Канал"],
                    ["ocr", "OCR"],
                    ["motion", "Движение"],
                    ["controller", "Контроллер"],
                  ].map(([id, label]) => (
                    <Button key={id} variant={channelTab === id ? "default" : "outline"} className="rounded-2xl" onClick={() => setChannelTab(id)}>
                      {label}
                    </Button>
                  ))}
                </div>
              </CardHeader>
              <CardContent className="space-y-4">
                {channelTab === "channel" ? (
                  <>
                    <Field label="Название" value={channel.name} theme={theme} />
                    <Field label="Источник / RTSP" value={channel.rtsp} theme={theme} />
                    <Field label="Лимит FPS предпросмотра" value={String(channel.fps)} theme={theme} />
                    <SelectField label="Фильтр направления" value="Оба направления" theme={theme} />
                    <SelectField label="Режим фильтра списков" value="Свои списки" theme={theme} />
                    <SelectField label="Выбрать списки" value="VIP, Служебные" theme={theme} />
                    <SelectField label="Зона" value={channel.zone} theme={theme} />
                    <SelectField label="Тип канала" value={channel.channelType} theme={theme} />
                  </>
                ) : null}

                {channelTab === "ocr" ? (
                  <>
                    <Field label="Бестшоты на трек" value="4" theme={theme} />
                    <Field label="Пауза повтора (сек)" value="8" theme={theme} />
                    <Field label="Мин. уверенность OCR" value="0.85" theme={theme} />
                    <Field label="Макс. OCR попыток на трек" value="12" theme={theme} />
                    <Field label="Пустых OCR подряд до завершения трека" value="5" theme={theme} />
                  </>
                ) : null}

                {channelTab === "motion" ? (
                  <>
                    <SelectField label="Режим обнаружения ТС" value="motion" theme={theme} />
                    <Field label="Порог движения" value="0.18" theme={theme} />
                    <Field label="Частота анализа (кадр)" value="2" theme={theme} />
                    <Field label="Мин. кадров с движением" value="3" theme={theme} />
                    <Field label="Мин. кадров без движения" value="6" theme={theme} />
                    <Field label="Шаг инференса (кадр)" value="3" theme={theme} />
                    <ToggleField label="Адаптивный шаг инференса" checked={true} theme={theme} />
                    <ToggleField label="Фильтрация размеров" checked={true} theme={theme} />
                    <Field label="Мин. размер рамки (ш,в)" value="160 × 40" theme={theme} />
                    <Field label="Макс. размер рамки (ш,в)" value="420 × 140" theme={theme} />
                    <ToggleField label="Использование ROI" checked={true} theme={theme} />
                  </>
                ) : null}

                {channelTab === "controller" ? (
                  <>
                    <SelectField label="Контроллер" value="Шлагбаум север" theme={theme} />
                    <SelectField label="Реле" value="Реле 1" theme={theme} />
                  </>
                ) : null}

                <Button className="rounded-2xl">Сохранить канал</Button>
              </CardContent>
            </Card>
          </div>
        ) : null}

        {pane === "controllers" ? (
          <div className="grid gap-4 xl:grid-cols-[280px_minmax(0,1fr)]">
            <Card className={panelClass(theme)}>
              <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-3">
                <CardTitle className="text-base">Контроллеры</CardTitle>
                <div className="flex gap-2">
                  <Button variant="outline" className="h-9 w-9 rounded-xl p-0"><Plus className="h-4 w-4" /></Button>
                  <Button variant="outline" className="h-9 w-9 rounded-xl p-0"><Minus className="h-4 w-4" /></Button>
                </div>
              </CardHeader>
              <CardContent className="space-y-3">
                {controllers.map((item) => (
                  <SidebarListItem
                    key={item.id}
                    active={item.id === selectedControllerId}
                    onClick={() => setSelectedControllerId(item.id)}
                    title={item.name}
                    subtitle={`${item.type} · ${item.address}`}
                    right={<MinimalBadge className={neutralBadgeClass(theme)}>2CH</MinimalBadge>}
                    theme={theme}
                  />
                ))}
              </CardContent>
            </Card>

            <Card className={panelClass(theme)}>
              <CardHeader className="pb-3">
                <SectionEyebrow theme={theme}>Параметры контроллера</SectionEyebrow>
                <CardTitle className="text-base">{controller.name}</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <Field label="Название" value={controller.name} theme={theme} help={false} />
                <SelectField label="Тип" value={controller.type} theme={theme} help={false} />
                <Field label="Адрес" value={controller.address} theme={theme} help={false} />
                <Field label="Пароль" value="••••••••" theme={theme} help={false} />

                <div className={cn("rounded-2xl border p-4", softBlockClass(theme))}>
                  <div className={cn("mb-3 text-sm font-semibold", textPrimary(theme))}>Реле 1</div>
                  <div className="space-y-4">
                    <SelectField label="Режим" value={controller.relay1Mode} theme={theme} help={false} />
                    <Field label="Задержка (сек)" value={String(controller.relay1Delay)} theme={theme} help={false} />
                    <Field label="Хоткей" value={controller.relay1Hotkey} theme={theme} help={false} />
                    <Button variant="outline" className="rounded-2xl">Тест реле 1</Button>
                  </div>
                </div>

                <div className={cn("rounded-2xl border p-4", softBlockClass(theme))}>
                  <div className={cn("mb-3 text-sm font-semibold", textPrimary(theme))}>Реле 2</div>
                  <div className="space-y-4">
                    <SelectField label="Режим" value={controller.relay2Mode} theme={theme} help={false} />
                    <Field label="Задержка (сек)" value={String(controller.relay2Delay)} theme={theme} help={false} />
                    <Field label="Хоткей" value={controller.relay2Hotkey} theme={theme} help={false} />
                    <Button variant="outline" className="rounded-2xl">Тест реле 2</Button>
                  </div>
                </div>

                <Button className="rounded-2xl">Сохранить контроллер</Button>
              </CardContent>
            </Card>
          </div>
        ) : null}

        {pane === "users" ? (
          <div className="grid gap-4 xl:grid-cols-[280px_minmax(0,1fr)]">
            <Card className={panelClass(theme)}>
              <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-3">
                <CardTitle className="text-base">Пользователи</CardTitle>
                <Button className="rounded-2xl">+</Button>
              </CardHeader>
              <CardContent className="space-y-3">
                {users.map((item) => (
                  <SidebarListItem
                    key={item.id}
                    active={item.id === selectedUserId}
                    onClick={() => setSelectedUserId(item.id)}
                    title={item.login}
                    subtitle={item.role}
                    right={<MinimalBadge className={item.active ? successBadgeClass(theme) : neutralBadgeClass(theme)}>{item.active ? "Активен" : "Откл."}</MinimalBadge>}
                    theme={theme}
                  />
                ))}
              </CardContent>
            </Card>

            <Card className={panelClass(theme)}>
              <CardHeader className="pb-3">
                <SectionEyebrow theme={theme}>Параметры пользователя</SectionEyebrow>
                <CardTitle className="text-base">{user.login}</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <Field label="Логин" value={user.login} theme={theme} help={false} />
                <SelectField label="Роль" value={user.role} theme={theme} help={false} />
                <SelectField label="Доступные вкладки" value={user.tabs.join(", ")} theme={theme} help={false} />
                <ToggleField label="Активен" checked={user.active} theme={theme} help={false} />
                <Button variant="outline" className="rounded-2xl">Сменить пароль</Button>
                <Button className="rounded-2xl">Сохранить</Button>
              </CardContent>
            </Card>
          </div>
        ) : null}

        {pane === "sysdata" ? (
          <div className="grid gap-4 md:grid-cols-2">
            <Card className={panelClass(theme)}>
              <CardHeader className="pb-3">
                <SectionEyebrow theme={theme}>База данных</SectionEyebrow>
                <CardTitle className="text-base">Экспорт / импорт БД</CardTitle>
              </CardHeader>
              <CardContent className="flex flex-wrap gap-2">
                <Button className="rounded-2xl"><Download className="mr-2 h-4 w-4" />Экспорт БД</Button>
                <Button variant="outline" className="rounded-2xl"><Upload className="mr-2 h-4 w-4" />Импорт БД</Button>
              </CardContent>
            </Card>

            <Card className={panelClass(theme)}>
              <CardHeader className="pb-3">
                <SectionEyebrow theme={theme}>Конфигурация</SectionEyebrow>
                <CardTitle className="text-base">Экспорт / импорт настроек</CardTitle>
              </CardHeader>
              <CardContent className="flex flex-wrap gap-2">
                <Button className="rounded-2xl"><Download className="mr-2 h-4 w-4" />Экспорт настроек</Button>
                <Button variant="outline" className="rounded-2xl"><Upload className="mr-2 h-4 w-4" />Импорт настроек</Button>
              </CardContent>
            </Card>
          </div>
        ) : null}

        {pane === "debug" ? (
          <Card className={panelClass(theme)}>
            <CardHeader className="pb-3">
              <SectionEyebrow theme={theme}>Разработка</SectionEyebrow>
              <CardTitle className="text-base">Настройки отладки</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <ToggleField label="Показывать метрики каналов" checked={true} theme={theme} help={false} />
              <ToggleField label="Панель логов включена" checked={true} theme={theme} help={false} />
              <ToggleField label="Отключить видеовыход (снизить нагрузку CPU)" checked={false} theme={theme} help={false} />
              <div className={cn("rounded-2xl border p-4 font-mono text-xs", softBlockClass(theme), textMuted(theme))}>
                <div>[14:02:18] debug: live log stream connected</div>
                <div>[14:02:19] overlay polling: enabled</div>
                <div>[14:02:20] channel 5 video output disabled = false</div>
              </div>
              <Button className="rounded-2xl">Сохранить</Button>
            </CardContent>
          </Card>
        ) : null}
      </div>
    </div>
  );
}

export default function AnprCleanDashboardConcept() {
  const [theme, setTheme] = useState("light");
  const [role, setRole] = useState("superadmin");
  const [activeTab, setActiveTab] = useState("obs");
  const [selectedEvent, setSelectedEvent] = useState(null);

  const title = useMemo(() => tabs.find((t) => t.id === activeTab)?.label ?? "ANPR", [activeTab]);

  const content = {
    obs: <ObservationView theme={theme} role={role} selectedEvent={selectedEvent} setSelectedEvent={setSelectedEvent} />,
    journal: <JournalView theme={theme} />,
    zones: <ZonesView theme={theme} />,
    clients: <ClientsView theme={theme} />,
    settings: <SettingsView theme={theme} role={role} />,
  };

  return (
    <>
      <AppFrame theme={theme}>
        <Rail activeTab={activeTab} setActiveTab={setActiveTab} theme={theme} role={role} />

        <div className="flex min-w-0 flex-1 flex-col">
          <header className={cn("border-b px-4 py-4 md:px-6", surface(theme, "border-white/10 bg-slate-900", "border-slate-200 bg-white"))}>
            <div className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
              <div>
                <div className={cn("mb-1 text-sm", textSecondary(theme))}>ANPR System · Web UI</div>
                <div className={cn("text-2xl font-semibold tracking-tight", textPrimary(theme))}>{title}</div>
              </div>

              <div className="grid gap-3 sm:grid-cols-2 xl:flex xl:items-center">
                <MetricPill icon={Cpu} label="CPU" value="12%" theme={theme} />
                <MetricPill icon={Gauge} label="RAM" value="29%" theme={theme} />
                <MetricPill icon={LayoutGrid} label="Каналы" value="4 online" theme={theme} />
                <MetricPill icon={Server} label="Сервер" value="Стабильно" theme={theme} />
                <MetricPill icon={Clock3} label="Время" value="17 апр 2026 · 14:02" theme={theme} />
                <div className="flex gap-2">
                  {[
                    ["operator", "Оператор"],
                    ["admin", "Админ"],
                    ["superadmin", "Супер"],
                  ].map(([value, label]) => (
                    <Button key={value} variant={role === value ? "default" : "outline"} className="rounded-2xl" onClick={() => setRole(value)}>
                      {label}
                    </Button>
                  ))}
                </div>
                <Button variant="outline" className="rounded-2xl" onClick={() => setTheme((t) => (t === "dark" ? "light" : "dark"))}>
                  {theme === "dark" ? <SunMedium className="mr-2 h-4 w-4" /> : <Moon className="mr-2 h-4 w-4" />}
                  {theme === "dark" ? "Светлая" : "Тёмная"}
                </Button>
              </div>
            </div>
          </header>

          <main className="min-h-0 flex-1 p-4 pb-24 md:p-6 md:pb-28 lg:pb-6">
            {content[activeTab]}
          </main>
        </div>
      </AppFrame>

      <Modal
        open={Boolean(selectedEvent)}
        onClose={() => setSelectedEvent(null)}
        title="Детальный просмотр события"
        theme={theme}
        footer={<Button className="rounded-2xl" onClick={() => setSelectedEvent(null)}>Закрыть</Button>}
      >
        {selectedEvent ? (
          <div className="space-y-4">
            <div className="grid gap-4 md:grid-cols-2">
              <div className={cn("aspect-video rounded-2xl border", softBlockClass(theme))} />
              <div className={cn("aspect-video rounded-2xl border", softBlockClass(theme))} />
            </div>
            <div className="grid gap-3 md:grid-cols-2">
              <div className={cn("p-4", softBlockClass(theme))}>
                <div className={cn("mb-1 text-xs", textSecondary(theme))}>Канал</div>
                <div className={cn("text-sm font-semibold", textPrimary(theme))}>{selectedEvent.channel}</div>
              </div>
              <div className={cn("p-4", softBlockClass(theme))}>
                <div className={cn("mb-1 text-xs", textSecondary(theme))}>Номер</div>
                <div className={cn("text-sm font-semibold font-mono", textPrimary(theme))}>{selectedEvent.plate}</div>
              </div>
              <div className={cn("p-4", softBlockClass(theme))}>
                <div className={cn("mb-1 text-xs", textSecondary(theme))}>Зона</div>
                <div className={cn("text-sm font-semibold", textPrimary(theme))}>{selectedEvent.zone}</div>
              </div>
              <div className={cn("p-4", softBlockClass(theme))}>
                <div className={cn("mb-1 text-xs", textSecondary(theme))}>Уверенность</div>
                <div className={cn("text-sm font-semibold", textPrimary(theme))}>{selectedEvent.confidence}</div>
              </div>
            </div>
          </div>
        ) : null}
      </Modal>
    </>
  );
}

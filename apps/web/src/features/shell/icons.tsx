import type { ReactNode } from "react";

/** Thin line icons, drawn inline so the bundle carries no icon dependency. */
function Svg({ children }: { children: ReactNode }) {
  return (
    <svg
      className="rail-icon"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {children}
    </svg>
  );
}

export const IconCommand = () => (
  <Svg>
    <rect x="3" y="3" width="7" height="7" rx="1.5" />
    <rect x="14" y="3" width="7" height="7" rx="1.5" />
    <rect x="3" y="14" width="7" height="7" rx="1.5" />
    <rect x="14" y="14" width="7" height="7" rx="1.5" />
  </Svg>
);

export const IconChat = () => (
  <Svg>
    <path d="M21 12a8 8 0 0 1-8 8H8l-4 3v-4.5A8 8 0 0 1 13 4a8 8 0 0 1 8 8Z" />
  </Svg>
);

export const IconTasks = () => (
  <Svg>
    <path d="M9 6h11M9 12h11M9 18h11" />
    <path d="M4 5.5 5.5 7 8 4.5M4 11.5 5.5 13 8 10.5M4 17.5 5.5 19 8 16.5" />
  </Svg>
);

export const IconShield = () => (
  <Svg>
    <path d="M12 3 5 6v6c0 4.5 3 7.8 7 9 4-1.2 7-4.5 7-9V6l-7-3Z" />
    <path d="m9 12 2 2 4-4" />
  </Svg>
);

export const IconCore = () => (
  <Svg>
    <circle cx="12" cy="12" r="8" />
    <circle cx="12" cy="12" r="3" />
    <path d="M12 2v3M12 19v3M2 12h3M19 12h3" />
  </Svg>
);

export const IconTools = () => (
  <Svg>
    <path d="M14.5 6.5a3.5 3.5 0 0 1 4.9 4.5l-8.2 8.2a2.5 2.5 0 0 1-3.5 0l-1.4-1.4a2.5 2.5 0 0 1 0-3.5Z" />
    <path d="m5 5 3 3M19 19l-2.5-2.5" />
  </Svg>
);

export const IconMemory = () => (
  <Svg>
    <rect x="4" y="7" width="16" height="12" rx="2" />
    <path d="M8 7V4M16 7V4M8 19v2M16 19v2M9 12h6" />
  </Svg>
);

export const IconChart = () => (
  <Svg>
    <path d="M4 20V10M10 20V6M16 20v-7M22 20H2" />
  </Svg>
);

export const IconMic = () => (
  <Svg>
    <rect x="9" y="3" width="6" height="11" rx="3" />
    <path d="M5 11a7 7 0 0 0 14 0M12 18v3M8 21h8" />
  </Svg>
);

export const IconSpark = () => (
  <Svg>
    <path d="M12 3v4M12 17v4M3 12h4M17 12h4M6 6l2.5 2.5M15.5 15.5 18 18M18 6l-2.5 2.5M8.5 15.5 6 18" />
  </Svg>
);

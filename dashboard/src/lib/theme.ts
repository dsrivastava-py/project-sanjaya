// Theme state: dark is the default and the brand home (§4.1). Persisted; applied
// before first paint by the inline script in index.html.
import { useCallback, useEffect, useState } from "react";

import type { ThemeName } from "./palette";

export function useTheme(): [ThemeName, () => void] {
  const [theme, setTheme] = useState<ThemeName>(
    () => (document.documentElement.dataset.theme as ThemeName) || "dark",
  );

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try {
      localStorage.setItem("sanjaya-theme", theme);
    } catch {
      /* private mode — theme just won't persist */
    }
  }, [theme]);

  const toggle = useCallback(() => setTheme((t) => (t === "dark" ? "light" : "dark")), []);
  return [theme, toggle];
}

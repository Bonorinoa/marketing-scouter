import { createRoot } from "react-dom/client";
import "@fontsource/inter-tight/latin-400.css";
import "@fontsource/inter-tight/latin-600.css";
import "@fontsource/jetbrains-mono/latin-400.css";
import "@fontsource/jetbrains-mono/latin-600.css";
import App from "./App";
import "./tokens.css";
import "./styles.css";

createRoot(document.getElementById("root")!).render(<App />);

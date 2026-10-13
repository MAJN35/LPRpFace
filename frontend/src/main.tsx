import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { App } from "./App";
import { registerWorker } from "./components/systemNotify";
import { I18nProvider } from "./i18n";
import "./tokens.css";

registerWorker();
ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode><I18nProvider><BrowserRouter><App /></BrowserRouter></I18nProvider></React.StrictMode>,
);

// Copy text: Clipboard API where the page is a secure context, else the legacy selection copy (the dashboard is
// often opened over plain http on the LAN, where navigator.clipboard is missing). Rejects when nothing was copied.
export async function copyText(text: string): Promise<void> {
  if (navigator.clipboard && window.isSecureContext) return navigator.clipboard.writeText(text);
  const ta = document.createElement("textarea");
  ta.value = text; ta.setAttribute("readonly", ""); ta.style.position = "fixed"; ta.style.opacity = "0";
  document.body.appendChild(ta); ta.select();
  const ok = document.execCommand("copy");
  ta.remove();
  if (!ok) throw new Error("copy failed");
}

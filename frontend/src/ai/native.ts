import { Capacitor, registerPlugin } from "@capacitor/core";
import type { AiTransport, CredentialStatus, Provider, WireMessage, Answer } from "./model";
import { DEFAULT_PROVIDER } from "./model";
interface AgnesBridge {
  status(): Promise<Omit<CredentialStatus, "available">>;
  configure(options: { key: string; persist: boolean; provider: Provider; consent: true }): Promise<Omit<CredentialStatus, "available">>;
  remove(): Promise<Omit<CredentialStatus, "available">>;
  send(options: { requestId: string; messages: WireMessage[]; stream: boolean; consent: true }): Promise<Answer>;
  cancel(options: { requestId: string }): Promise<void>;
  addListener(name: "chunk", listener: (event: { requestId: string; text: string }) => void): Promise<{ remove(): Promise<void> }>;
}
const native = registerPlugin<AgnesBridge>("AgnesAI");
function requireAndroid() { if (Capacitor.getPlatform() !== "android") throw { code: "UNAVAILABLE" }; }
export function nativeTransport(): AiTransport {
  return {
    async status() { if (Capacitor.getPlatform() !== "android") return { available: false, configured: false, persistent: false, provider: DEFAULT_PROVIDER }; return { ...await native.status(), available: true }; },
    async configure(key, persist, provider) { requireAndroid(); return { ...await native.configure({ key, persist, provider, consent: true }), available: true }; },
    async remove() { requireAndroid(); return { ...await native.remove(), available: true }; },
    async send(requestId, messages, stream) { requireAndroid(); return native.send({ requestId, messages, stream, consent: true }); },
    async cancel(requestId) { requireAndroid(); await native.cancel({ requestId }); },
    async chunks(listener) {
      if (Capacitor.getPlatform() !== "android") return () => {};
      const subscription = await native.addListener("chunk", event => listener(event.requestId, event.text));
      return () => { void subscription.remove(); };
    },
  };
}

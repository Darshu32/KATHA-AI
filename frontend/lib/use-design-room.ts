"use client";

/* useDesignRoom — real-time collaborative editing over Yjs.
 *
 * Connects a Y.Doc to the project's backend room (app.services.collab) via
 * y-websocket. Object positions live in a shared Y.Map "objects" (id → Y.Map of
 * {x,y,z}); a drag in one client writes the map, and every other client's
 * `positions` updates live. The server seeds the room from the latest saved
 * version and snapshots it back to the DB on disconnect, so this layer is
 * additive — the editor still works (solo) when a room isn't connected. */

import { useEffect, useRef, useState } from "react";
import * as Y from "yjs";
import { WebsocketProvider } from "y-websocket";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";
const WS_BASE = `${API_BASE.replace(/^http/, "ws")}/ws/design`;

export type RoomPos = { x: number; y: number; z: number };

export interface DesignRoom {
  /** Live positions from the shared doc, keyed by object id. */
  positions: Record<string, RoomPos>;
  /** Write a position to the shared doc (syncs to peers, persisted on disconnect). */
  setPosition: (id: string, pos: Partial<RoomPos>) => void;
  /** Connected collaborators (>=1 when connected). */
  peers: number;
  connected: boolean;
}

export function useDesignRoom(
  projectId: string | null,
  token: string,
  enabled: boolean,
): DesignRoom {
  const docRef = useRef<Y.Doc | null>(null);
  const objectsRef = useRef<Y.Map<Y.Map<number>> | null>(null);
  const [positions, setPositions] = useState<Record<string, RoomPos>>({});
  const [peers, setPeers] = useState(1);
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    if (!enabled || !projectId) return;

    const doc = new Y.Doc();
    const objects = doc.getMap<Y.Map<number>>("objects");
    docRef.current = doc;
    objectsRef.current = objects;

    const provider = new WebsocketProvider(WS_BASE, projectId, doc, {
      params: token ? { token } : {},
    });
    // Register this client in awareness so peers can be counted / shown.
    provider.awareness.setLocalStateField("client", { online: true });

    const readAll = () => {
      const out: Record<string, RoomPos> = {};
      objects.forEach((m, id) => {
        out[id] = {
          x: Number(m.get("x") ?? 0),
          y: Number(m.get("y") ?? 0),
          z: Number(m.get("z") ?? 0),
        };
      });
      setPositions(out);
    };

    // observeDeep fires on object add/remove AND any nested position change.
    objects.observeDeep(readAll);
    const onStatus = (e: { status: string }) => setConnected(e.status === "connected");
    const onSync = (synced: boolean) => {
      if (synced) readAll();
    };
    provider.on("status", onStatus);
    provider.on("sync", onSync);
    const { awareness } = provider;
    const onAware = () => setPeers(Math.max(1, awareness.getStates().size));
    awareness.on("change", onAware);

    return () => {
      objects.unobserveDeep(readAll);
      provider.off("status", onStatus);
      provider.off("sync", onSync);
      awareness.off("change", onAware);
      provider.destroy();
      doc.destroy();
      docRef.current = null;
      objectsRef.current = null;
    };
  }, [enabled, projectId, token]);

  const setPosition = (id: string, pos: Partial<RoomPos>) => {
    const objects = objectsRef.current;
    const doc = docRef.current;
    if (!objects || !doc) return;
    doc.transact(() => {
      let m = objects.get(id);
      if (!m) {
        m = new Y.Map<number>();
        objects.set(id, m);
      }
      if (pos.x !== undefined) m.set("x", pos.x);
      if (pos.y !== undefined) m.set("y", pos.y);
      if (pos.z !== undefined) m.set("z", pos.z);
    });
  };

  return { positions, setPosition, peers, connected };
}

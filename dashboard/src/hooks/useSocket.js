import { useEffect, useRef, useState, useCallback } from "react";
import io from "socket.io-client";
import { BASE } from "../api/client";

export function useSocket({ onNewUser, onUserUpdate, onNewMessage, onStatusUpdate, onModeChanged, onUserUpdated }) {
  const socketRef = useRef(null);
  const [connected, setConnected] = useState(false);

  // Stable refs so socket listeners always see current callbacks
  const cbRefs = useRef({});
  cbRefs.current = { onNewUser, onUserUpdate, onNewMessage, onStatusUpdate, onModeChanged, onUserUpdated };

  useEffect(() => {
    const socket = io(BASE, {
      transports: ["websocket", "polling"],
      reconnection: true,
      reconnectionAttempts: 10,
    });
    socketRef.current = socket;

    socket.on("connect", () => setConnected(true));
    socket.on("disconnect", () => setConnected(false));
    socket.on("new_user", (d) => cbRefs.current.onNewUser?.(d));
    socket.on("user_update", (d) => cbRefs.current.onUserUpdate?.(d));
    socket.on("new_message", (d) => cbRefs.current.onNewMessage?.(d));
    socket.on("status_update", (d) => cbRefs.current.onStatusUpdate?.(d));
    socket.on("mode_changed", (d) => cbRefs.current.onModeChanged?.(d));
    socket.on("user_updated", (d) => cbRefs.current.onUserUpdated?.(d));

    return () => socket.disconnect();
  }, []); // run once — stable refs handle latest callbacks

  return { connected };
}

import { useState, useCallback, useRef } from "react";
import { api } from "../api/client";

export function useMessages(selectedPhone) {
  const [messages, setMessages] = useState([]);
  const [loading, setLoading] = useState(false);
  const [unreadCounts, setUnreadCounts] = useState({});
  const [highlightedUsers, setHighlightedUsers] = useState(new Set());
  const selectedPhoneRef = useRef(selectedPhone);
  selectedPhoneRef.current = selectedPhone;

  const loadMessages = useCallback(async (phone, search = "") => {
    if (!phone) return;
    setLoading(true);
    try {
      const data = await api.getMessages(phone, search);
      setMessages(data);
      markAsRead(phone);
    } catch (e) {
      console.error("loadMessages:", e);
    } finally {
      setLoading(false);
    }
  }, []);

  const markAsRead = useCallback((phone) => {
    setUnreadCounts((prev) => ({ ...prev, [phone]: 0 }));
    setHighlightedUsers((prev) => {
      const s = new Set(prev);
      s.delete(phone);
      return s;
    });
  }, []);

  const incrementUnread = useCallback((phone) => {
    if (selectedPhoneRef.current === phone) return;
    setUnreadCounts((prev) => ({ ...prev, [phone]: (prev[phone] || 0) + 1 }));
    setHighlightedUsers((prev) => new Set(prev).add(phone));
  }, []);

  const appendMessage = useCallback((msg) => {
    setMessages((prev) => [...prev, msg]);
  }, []);

  const updateMessageStatus = useCallback((waId, status) => {
    if (!waId) return;
    setMessages((prev) => {
      // Try to find message by whatsapp_message_id
      const hasMatch = prev.some(
        (m) => m.whatsapp_message_id && m.whatsapp_message_id === waId
      );

      if (hasMatch) {
        return prev.map((m) =>
          m.whatsapp_message_id === waId ? { ...m, status } : m
        );
      }

      // Fallback — update the most recent bot message that doesn't have
      // a whatsapp_message_id yet (optimistic message waiting for confirmation)
      const lastBotIndex = [...prev]
        .reverse()
        .findIndex((m) => m.direction === "bot" && !m.whatsapp_message_id);

      if (lastBotIndex !== -1) {
        const realIndex = prev.length - 1 - lastBotIndex;
        return prev.map((m, i) =>
          i === realIndex
            ? { ...m, status, whatsapp_message_id: waId }
            : m
        );
      }

      return prev;
    });
  }, []);

  const updateTempStatus = useCallback((tempId, status) => {
    setMessages((prev) =>
      prev.map((m) => (m._id === tempId ? { ...m, status } : m))
    );
  }, []);

  const removeMessage = useCallback((ref) => {
    setMessages((prev) => prev.filter((m) => m !== ref));
  }, []);

  return {
    messages,
    setMessages,
    loading,
    unreadCounts,
    highlightedUsers,
    loadMessages,
    markAsRead,
    incrementUnread,
    appendMessage,
    updateMessageStatus,
    updateTempStatus,
    removeMessage,
    selectedPhoneRef,
  };
}
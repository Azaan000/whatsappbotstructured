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
    setMessages((prev) =>
      prev.map((m) =>
        m.whatsapp_message_id === waId ? { ...m, status } : m
      )
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
    removeMessage,
    selectedPhoneRef,
  };
}
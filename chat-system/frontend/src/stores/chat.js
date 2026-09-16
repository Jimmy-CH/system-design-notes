import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import axios from 'axios'

const API_BASE = '/api'

export const useChatStore = defineStore('chat', () => {
  const friends = ref([])
  const groups = ref([])
  const conversations = ref({})  // channelId -> messages[]
  const activeChannel = ref(null) // { type: 'one_to_one'|'group', id: string, name: string }
  const onlineStatuses = ref({}) // userId -> 'online'|'offline'

  async function fetchFriends() {
    const res = await axios.get(`${API_BASE}/friends`)
    friends.value = res.data
    res.data.forEach(f => {
      onlineStatuses.value[f.user_id] = f.online_status
    })
  }

  async function fetchGroups() {
    try {
      const res = await axios.get(`${API_BASE}/groups/my-groups`)
      groups.value = res.data
    } catch {
      groups.value = []
    }
  }

  async function loadMessages(channelId, channelType) {
    let url
    if (channelType === 'one_to_one') {
      url = `${API_BASE}/channels/${channelId}/messages`
    } else {
      url = `${API_BASE}/groups/${channelId}/messages`
    }
    const res = await axios.get(url)
    conversations.value[channelId] = res.data
  }

  function addMessage(channelId, message) {
    if (!conversations.value[channelId]) {
      conversations.value[channelId] = []
    }
    conversations.value[channelId].push(message)
  }

  function setActiveChannel(type, id, name) {
    activeChannel.value = { type, id, name }
  }

  function updateOnlineStatus(userId, status) {
    onlineStatuses.value[userId] = status
  }

  return {
    friends, groups, conversations, activeChannel, onlineStatuses,
    fetchFriends, fetchGroups, loadMessages, addMessage,
    setActiveChannel, updateOnlineStatus,
  }
})

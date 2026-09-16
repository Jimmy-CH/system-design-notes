<template>
  <div class="chat-layout">
    <ChatSidebar
      :friends="chatStore.friends"
      :groups="chatStore.groups"
      :online-statuses="chatStore.onlineStatuses"
      :active-channel="chatStore.activeChannel"
      @select-friend="selectFriend"
      @select-group="selectGroup"
      @start-chat="startChat"
      @show-groups="showGroupPanel = true"
    />

    <ChatWindow
      :channel="chatStore.activeChannel"
      :messages="currentMessages"
      :current-user-id="currentUserId"
      :peer-status="peerStatus"
      @send="sendMessage"
      @typing="sendTyping"
    />

    <GroupPanel
      :visible="showGroupPanel"
      :groups="chatStore.groups"
      @close="showGroupPanel = false"
      @select-group="selectGroup"
      @group-created="refreshGroups"
    />
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useAuthStore } from '../stores/auth'
import { useChatStore } from '../stores/chat'
import { useWebSocket } from '../composables/useWebSocket'
import ChatSidebar from '../components/ChatSidebar.vue'
import ChatWindow from '../components/ChatWindow.vue'
import GroupPanel from '../components/GroupPanel.vue'

const authStore = useAuthStore()
const chatStore = useChatStore()
const showGroupPanel = ref(false)

const currentUserId = computed(() => authStore.user?.id || '')
const currentMessages = computed(() => {
  if (!chatStore.activeChannel) return []
  const id = chatStore.activeChannel.type === 'one_to_one'
    ? getChannelId(chatStore.activeChannel.id)
    : chatStore.activeChannel.id
  return chatStore.conversations[id] || []
})

const peerStatus = computed(() => {
  if (chatStore.activeChannel?.type === 'one_to_one') {
    return chatStore.onlineStatuses[chatStore.activeChannel.id] || 'offline'
  }
  return 'offline'
})

// WebSocket setup
const ws = useWebSocket(authStore.token)

function getChannelId(otherUserId) {
  const ids = [currentUserId.value, otherUserId].sort()
  return ids.join('_')
}

function selectFriend(friend) {
  const channelId = getChannelId(friend.user_id)
  chatStore.setActiveChannel('one_to_one', friend.user_id, friend.nickname || friend.username)
  chatStore.loadMessages(channelId, 'one_to_one')
}

function selectGroup(group) {
  chatStore.setActiveChannel('group', group.id, group.name)
  chatStore.loadMessages(group.id, 'group')
  showGroupPanel.value = false
}

function startChat(user) {
  selectFriend({ user_id: user.id, nickname: user.nickname, username: user.username, online_status: 'offline' })
}

function sendMessage(content) {
  if (!chatStore.activeChannel) return
  const receiverId = chatStore.activeChannel.id
  const channelType = chatStore.activeChannel.type
  ws.sendMessage(receiverId, content, channelType)
}

function sendTyping() {
  // Could send typing indicator
}

async function refreshGroups() {
  await chatStore.fetchGroups()
}

onMounted(async () => {
  await authStore.fetchProfile()
  ws.connect()
  await chatStore.fetchFriends()
  await chatStore.fetchGroups()
})
</script>

<style scoped>
.chat-layout {
  display: flex;
  height: 100vh;
  background: #f0f2f5;
}
</style>

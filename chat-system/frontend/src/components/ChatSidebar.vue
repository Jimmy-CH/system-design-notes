<template>
  <div class="sidebar">
    <div class="sidebar-header">
      <h2>Chats</h2>
      <div class="header-actions">
        <button @click="$emit('showGroups')" class="icon-btn" title="Groups">&#x1F465;</button>
        <button @click="$router.push('/profile')" class="icon-btn" title="Profile">&#x1F464;</button>
      </div>
    </div>

    <div class="search-box">
      <input v-model="searchQuery" placeholder="Search users..." @input="searchUsers" />
    </div>

    <!-- Search Results -->
    <div v-if="searchResults.length" class="section">
      <h3>Search Results</h3>
      <div v-for="user in searchResults" :key="user.id" class="contact"
           @click="$emit('startChat', user)">
        <OnlineIndicator :status="onlineStatuses[user.id] || 'offline'" />
        <span>{{ user.nickname || user.username }}</span>
      </div>
    </div>

    <!-- Friends List -->
    <div class="section">
      <h3>Friends</h3>
      <div v-for="friend in friends" :key="friend.user_id" class="contact"
           :class="{ active: activeChannel?.id === friend.user_id }"
           @click="$emit('selectFriend', friend)">
        <OnlineIndicator :status="friend.online_status" />
        <span>{{ friend.nickname || friend.username }}</span>
      </div>
      <p v-if="!friends.length" class="empty">No friends yet. Search for users above.</p>
    </div>

    <!-- Groups List -->
    <div class="section">
      <h3>Groups</h3>
      <div v-for="group in groups" :key="group.id" class="contact"
           :class="{ active: activeChannel?.id === group.id }"
           @click="$emit('selectGroup', group)">
        <span>&#x1F465; {{ group.name }}</span>
        <span class="badge">{{ group.member_count }}</span>
      </div>
      <p v-if="!groups.length" class="empty">No groups yet.</p>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import axios from 'axios'
import OnlineIndicator from './OnlineIndicator.vue'

const props = defineProps({
  friends: Array,
  groups: Array,
  onlineStatuses: Object,
  activeChannel: Object,
})

defineEmits(['selectFriend', 'selectGroup', 'startChat', 'showGroups'])

const searchQuery = ref('')
const searchResults = ref([])

async function searchUsers() {
  if (searchQuery.value.length < 1) {
    searchResults.value = []
    return
  }
  try {
    const res = await axios.get(`/api/users/search?q=${searchQuery.value}`)
    searchResults.value = res.data
  } catch {
    searchResults.value = []
  }
}
</script>

<style scoped>
.sidebar {
  width: 300px;
  background: white;
  border-right: 1px solid #e0e0e0;
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow-y: auto;
}

.sidebar-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 1rem;
  border-bottom: 1px solid #eee;
}

.sidebar-header h2 { font-size: 1.2rem; color: #333; }

.header-actions {
  display: flex;
  gap: 4px;
}

.icon-btn {
  background: none;
  border: none;
  font-size: 1.2rem;
  cursor: pointer;
}

.search-box {
  padding: 0.5rem 1rem;
}

.search-box input {
  width: 100%;
  padding: 0.5rem;
  border: 1px solid #ddd;
  border-radius: 20px;
  outline: none;
  font-size: 0.9rem;
}

.section {
  padding: 0.5rem 0;
}

.section h3 {
  padding: 0.25rem 1rem;
  font-size: 0.8rem;
  color: #999;
  text-transform: uppercase;
}

.contact {
  display: flex;
  align-items: center;
  padding: 0.75rem 1rem;
  cursor: pointer;
  transition: background 0.2s;
}

.contact:hover, .contact.active {
  background: #f0f2f5;
}

.empty {
  padding: 0.5rem 1rem;
  color: #999;
  font-size: 0.85rem;
}

.badge {
  margin-left: auto;
  background: #667eea;
  color: white;
  border-radius: 10px;
  padding: 2px 8px;
  font-size: 0.75rem;
}
</style>

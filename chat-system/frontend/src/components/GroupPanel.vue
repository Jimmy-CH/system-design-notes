<template>
  <div class="group-panel" v-if="visible">
    <div class="panel-header">
      <h3>Groups</h3>
      <button @click="$emit('close')" class="close-btn">&times;</button>
    </div>

    <!-- Create Group -->
    <div class="section">
      <h4>Create Group</h4>
      <input v-model="newGroupName" placeholder="Group name" />
      <input v-model="newGroupDesc" placeholder="Description (optional)" />
      <button @click="createGroup" :disabled="!newGroupName.trim()">Create</button>
    </div>

    <!-- My Groups -->
    <div class="section">
      <h4>My Groups</h4>
      <div v-for="group in groups" :key="group.id" class="group-item">
        <div>
          <strong>{{ group.name }}</strong>
          <p>{{ group.member_count }} members</p>
        </div>
        <button @click="$emit('selectGroup', group)">Open</button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import axios from 'axios'

const props = defineProps({
  visible: Boolean,
  groups: Array,
})

const emit = defineEmits(['close', 'selectGroup', 'groupCreated'])

const newGroupName = ref('')
const newGroupDesc = ref('')

async function createGroup() {
  if (!newGroupName.value.trim()) return
  try {
    await axios.post('/api/groups', {
      name: newGroupName.value,
      description: newGroupDesc.value || null,
    })
    newGroupName.value = ''
    newGroupDesc.value = ''
    emit('groupCreated')
  } catch (e) {
    alert(e.response?.data?.detail || 'Failed to create group')
  }
}
</script>

<style scoped>
.group-panel {
  position: fixed;
  right: 0;
  top: 0;
  width: 350px;
  height: 100vh;
  background: white;
  box-shadow: -4px 0 20px rgba(0,0,0,0.1);
  z-index: 100;
  overflow-y: auto;
  padding: 1rem;
}

.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 1rem;
}

.close-btn {
  background: none;
  border: none;
  font-size: 1.5rem;
  cursor: pointer;
  color: #666;
}

.section {
  margin-bottom: 1.5rem;
}

.section h4 {
  color: #333;
  margin-bottom: 0.5rem;
}

.section input {
  width: 100%;
  padding: 0.5rem;
  border: 1px solid #ddd;
  border-radius: 6px;
  margin-bottom: 0.5rem;
  outline: none;
}

.section button {
  width: 100%;
  padding: 0.5rem;
  background: #667eea;
  color: white;
  border: none;
  border-radius: 6px;
  cursor: pointer;
}

.section button:disabled {
  opacity: 0.5;
}

.group-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0.75rem;
  border: 1px solid #eee;
  border-radius: 8px;
  margin-bottom: 0.5rem;
}

.group-item button {
  width: auto;
  padding: 0.25rem 0.75rem;
}
</style>

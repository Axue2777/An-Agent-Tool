<script setup>
import { ref } from 'vue'

defineProps({ busy: Boolean })
const emit = defineEmits(['create', 'cancel'])
const title = ref('')
const assistantName = ref('助手')
const persona = ref('')
const files = ref([])

function selectFiles(event) {
  files.value = Array.from(event.target.files || [])
}

function submit() {
  emit('create', { title: title.value.trim() || null,
    assistant_name: assistantName.value.trim() || '助手',
    persona: persona.value.trim(), files: files.value })
}
</script>

<template>
  <!-- 弹窗挂到页面根部，避免顶部栏的背景模糊把 fixed 定位限制在栏内。 -->
  <Teleport to="body">
  <div class="setup-backdrop">
    <section class="setup-panel" role="dialog" aria-modal="true" aria-labelledby="setup-title">
      <h2 id="setup-title">新建聊天</h2>
      <form @submit.prevent="submit">
        <label>聊天名称（可留空）
          <input v-model="title" maxlength="60" :disabled="busy" />
        </label>
        <label>助手名字
          <input v-model="assistantName" maxlength="30" :disabled="busy" />
        </label>
        <label>角色与个性
          <!-- 角色描述由用户自由编写；留空时使用通用助手。 -->
          <textarea v-model="persona" maxlength="2000" rows="5" :disabled="busy"
            placeholder="例如：你是一位耐心的学习导师，请分步骤讲解；也可以留空。" />
        </label>
        <label>资料库文件（可稍后上传）
          <input type="file" multiple :disabled="busy" @change="selectFiles"
            accept=".txt,.md,.csv,.json,.py,.js,.ts,.vue,.html,.css,.xml,.yaml,.yml,.sql,.pdf,.docx,.xlsx,.pptx" />
        </label>
        <p v-if="files.length">已选择 {{ files.length }} 个文件</p>
        <div class="setup-actions">
          <button type="button" :disabled="busy" @click="emit('cancel')">取消</button>
          <button type="submit" :disabled="busy">{{ busy ? '创建中…' : '开始聊天' }}</button>
        </div>
      </form>
    </section>
  </div>
  </Teleport>
</template>

<style scoped>
.setup-backdrop { position: fixed; inset: 0; z-index: 100; display: grid; place-items: center; padding: 16px; background: rgb(0 0 0 / 40%); }
.setup-panel { box-sizing: border-box; width: min(520px, 100%); max-height: calc(100dvh - 32px); overflow: auto; padding: 20px; border: 1px solid #c8b9ed; border-radius: 20px; background: #fffdfb; color: #354063; }
.setup-panel h2 { margin: 0 0 16px; font-size: 18px; }
.setup-panel form, .setup-panel label { display: grid; gap: 8px; }
.setup-panel form { gap: 16px; }
.setup-panel input, .setup-panel textarea { box-sizing: border-box; width: 100%; min-width: 0; padding: 8px; border: 1px solid #c8c6e8; border-radius: 10px; background: #fcfbff; color: #354063; font: inherit; }
.setup-actions { display: flex; justify-content: flex-end; gap: 8px; }
.setup-actions button { min-height: 36px; padding: 6px 12px; cursor: pointer; }
</style>

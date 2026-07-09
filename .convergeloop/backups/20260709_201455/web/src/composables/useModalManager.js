import { ref, computed } from 'vue'

/**
 * Modal 状态机管理器
 * 替代多个 show*Modal ref，用单一 activeModal 状态管理
 */
export function useModalManager(modalNames) {
  const activeModal = ref(null)
  const modalData = ref({})

  function openModal(name, data = {}) {
    activeModal.value = name
    modalData.value = data
  }

  function closeModal() {
    activeModal.value = null
    modalData.value = {}
  }

  const modals = {}
  for (const name of modalNames) {
    modals[name] = {
      show: computed(() => activeModal.value === name),
      data: computed(() => activeModal.value === name ? modalData.value : {}),
      open: (data) => openModal(name, data),
      close: closeModal,
    }
  }

  return { modals, activeModal, closeModal }
}

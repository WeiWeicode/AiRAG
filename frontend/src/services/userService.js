import api from './api'

export default {
  // 部門 CRUD
  getDepartments() {
    return api.get('/api/users/departments')
  },
  createDepartment(name) {
    return api.post('/api/users/departments', { name })
  },
  deleteDepartment(id) {
    return api.delete(`/api/users/departments/${id}`)
  },

  // 使用者名冊 CRUD
  listUsers() {
    return api.get('/api/users')
  },
  createUser(data) {
    // data: { name, department, job_title, level }
    return api.post('/api/users', data)
  },
  deleteUser(id) {
    return api.delete(`/api/users/${id}`)
  }
}

import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import 'element-plus/dist/index.css'
import 'highlight.js/styles/atom-one-dark.css'
import App from './App.vue'
import router from './router'
import './styles/main.css'

const app = createApp(App)

app.use(createPinia())
app.use(router)
// Element Plus 中文语言包 + 统一组件层级（避免抽屉/对话框被自定义层级遮挡）
app.use(ElementPlus, { locale: zhCn, zIndex: 3000 })

app.mount('#app')

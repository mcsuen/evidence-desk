import {defineConfig} from '@playwright/test'
const port=process.env.PITR_BROWSER_PORT||'8879'
export default defineConfig({testDir:'./desk-tests',workers:1,timeout:30000,use:{baseURL:'http://127.0.0.1:'+port,channel:'chrome',headless:true,viewport:{width:1440,height:900},screenshot:'only-on-failure'},webServer:{command:'../.venv/bin/python ../tests/desk_browser_server.py',url:'http://127.0.0.1:'+port,reuseExistingServer:false,timeout:30000}})

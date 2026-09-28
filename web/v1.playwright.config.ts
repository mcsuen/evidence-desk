import {defineConfig} from '@playwright/test'
const port=process.env.PITR_BROWSER_PORT||'18879'
export default defineConfig({testDir:'./v1-tests',workers:1,timeout:45000,outputDir:process.env.PITR_BROWSER_OUTPUT||'test-results-v1',
 use:{baseURL:'http://127.0.0.1:'+port,channel:'chrome',headless:true,viewport:{width:1440,height:1000},screenshot:'only-on-failure'},
 webServer:{command:'../.venv/bin/python ../tests/v1/browser_server.py',url:'http://127.0.0.1:'+port,reuseExistingServer:false,timeout:45000}})

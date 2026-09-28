import {defineConfig} from '@playwright/test'
const port=process.env.PITR_RESTORATION_PORT||'18885'
export default defineConfig({testDir:'./restoration-tests',workers:1,timeout:45000,outputDir:'test-results-restoration',
 expect:{toHaveScreenshot:{maxDiffPixelRatio:.015,animations:'disabled'}},
 use:{baseURL:'http://127.0.0.1:'+port,channel:'chrome',headless:true,viewport:{width:1440,height:1000},screenshot:'only-on-failure'},
 webServer:{command:'PITR_UI_DEMO=1 PITR_BROWSER_PORT='+port+' ../.venv/bin/python ../tests/v1/browser_server.py',url:'http://127.0.0.1:'+port,reuseExistingServer:false,timeout:45000}})

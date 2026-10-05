/**
 * Test to verify if /api/system/health endpoint refreshes service status
 * 
 * Expected behavior: When calling /api/system/health, it should return fresh status
 * Current behavior: Returns cached status that only updates every 60 seconds
 */

const axios = require('axios');

const BACKEND_URL = 'http://localhost:3000';

async function testHealthRefresh() {
    console.log('测试健康检查刷新功能...\n');
    
    try {
        // First call
        console.log('第一次调用 /api/system/health...');
        const res1 = await axios.get(`${BACKEND_URL}/api/system/health`);
        console.log('服务状态:');
        console.log(JSON.stringify(res1.data.data.services, null, 2));
        console.log('\n最后检查时间:');
        for (const [name, status] of Object.entries(res1.data.data.services)) {
            console.log(`  ${name}: ${new Date(status.lastCheck).toLocaleTimeString()} (${status.lastCheck})`);
        }
        
        // Wait 2 seconds
        console.log('\n等待 2 秒...\n');
        await new Promise(resolve => setTimeout(resolve, 2000));
        
        // Second call - should trigger fresh health check
        console.log('第二次调用 /api/system/health (期望触发刷新)...');
        const res2 = await axios.get(`${BACKEND_URL}/api/system/health`);
        console.log('服务状态:');
        console.log(JSON.stringify(res2.data.data.services, null, 2));
        console.log('\n最后检查时间:');
        for (const [name, status] of Object.entries(res2.data.data.services)) {
            console.log(`  ${name}: ${new Date(status.lastCheck).toLocaleTimeString()} (${status.lastCheck})`);
        }
        
        // Compare timestamps
        console.log('\n\n=== 分析结果 ===');
        let refreshed = false;
        for (const [name, status1] of Object.entries(res1.data.data.services)) {
            const status2 = res2.data.data.services[name];
            const timeDiff = status2.lastCheck - status1.lastCheck;
            console.log(`${name}: 时间差 ${timeDiff}ms`);
            if (timeDiff > 100) {
                refreshed = true;
            }
        }
        
        if (refreshed) {
            console.log('\n✓ 状态已刷新 - 健康检查正常工作');
        } else {
            console.log('\n✗ 问题确认: 状态未刷新 - 返回的是缓存数据');
            console.log('   健康检查仅在定时任务中运行（每60秒），用户点击刷新按钮时不会触发实时检查');
        }
        
    } catch (error) {
        console.error('测试失败:', error.message);
        if (error.response) {
            console.error('响应状态:', error.response.status);
            console.error('响应数据:', error.response.data);
        }
    }
}

testHealthRefresh();

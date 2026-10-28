const {test}=require('node:test');
const assert=require('node:assert/strict');
const ops=require('../app/ui/operations.js');

test('dashboard totals use recorded allocations, not estimated imported workload',()=>{
  const summary=ops.summarize({workshops:[{status:'ACTIVE',queue_days:9,orders:[{remaining_pieces:80}]},{status:'SUSPENDED',queue_days:5,orders:[]}],orders:[{state:'WORKING'},{state:'COMPLETED'},{state:'READY'},{state:'LAPSED'}]});
  assert.equal(summary.active,1);assert.equal(summary.totalWorkshops,2);assert.equal(summary.outstanding,80);
  assert.equal(summary.working,1);assert.equal(summary.completed,1);assert.equal(summary.states.LAPSED,1);
});
test('empty and zero workloads produce finite zero bars',()=>{
  assert.deepEqual(ops.scales([]),[]);assert.deepEqual(ops.scales([0,0]),[0,0]);
  assert.deepEqual(ops.scales([2,4,0]),[50,100,0]);assert.equal(ops.summarize({}).outstanding,0);
});
test('partial completions and terminal completions have distinct timeline titles',()=>{
  assert.equal(ops.eventTitle({action:'complete',state_after:'WORKING'}),'Production progress recorded');
  assert.equal(ops.eventTitle({action:'complete',state_after:'COMPLETED'}),'Order completed');
  assert.equal(ops.eventTitle({action:'cancel'}),'Allocation cancelled');
  assert.equal(ops.eventTitle({action:'reassign'}),'Remaining pieces reassigned');
});

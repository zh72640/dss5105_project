const {test}=require('node:test');
const assert=require('node:assert/strict');
const client=require('../app/ui/chat-common.js');

function element(tag){return {tag,children:[],textContent:'',append(...nodes){this.children.push(...nodes);},addEventListener(){}};}
function flatten(node){return [node,...node.children.flatMap(flatten)];}
function render(callback){
  const previous=global.document;global.document={createElement:element};
  try{return callback();}finally{global.document=previous;}
}
const parts=[{workshop_id:'W1',workshop_name:'A',pieces:4,estimated_days:2,estimated_cost:4},
             {workshop_id:'W2',workshop_name:'B',pieces:4,estimated_days:3,estimated_cost:8}];
const plan={allocation:parts,estimated_delivery_date:'2026-04-04',estimated_cost:12,
            expected_defect_rate:.15,deadline_met:true};

test('split recommendations render complete plans even with no single-workshop ranking',()=>{
  const card=render(()=>client.card({status:'valid',result:{...plan,candidate_ranking:[],candidate_plans:[plan]}},()=>{}));
  const nodes=flatten(card),content=nodes.map(n=>n.textContent).join(' ');
  assert.match(content,/Compare complete candidate plans/);
  assert.match(content,/W1 \(4 pieces\) \+ W2 \(4 pieces\)/);
  assert.match(content,/15\.00%/);
  assert.equal(nodes.filter(n=>n.tag==='button').length,1);
});

test('conditional alternatives show explicit changes without an approval button',()=>{
  const option={plan,required_changes:{preferred_workshop:null,num_workshop_allowed:2},supported_mode:'offline'};
  const nodes=flatten(render(()=>client.alternatives([option])));
  const content=nodes.map(n=>n.textContent).join(' ');
  assert.match(content,/Remove the required sole workshop/);
  assert.match(content,/Allow up to 2 workshops/);
  assert.match(content,/requirements have not changed/);
  assert.match(content,/Offline mode only/);
  assert.equal(nodes.filter(n=>n.tag==='button').length,0);
});

test('review changes show old and new allocations and explain that nothing committed',()=>{
  const nodes=flatten(render(()=>client.reviewChanges([
    {field:'allocation',before:[parts[0]],after:[parts[1]]},
    {field:'estimated_cost',before:4,after:8},
    {field:'expected_defect_rate',before:.05,after:.04},
  ])));
  const content=nodes.map(n=>n.textContent).join(' ');
  assert.match(content,/W1: 4 pieces/);assert.match(content,/W2: 4 pieces/);
  assert.match(content,/Cost: 4\.00 → 8\.00/);
  assert.match(content,/Weighted defect rate: 5\.00% → 4\.00%/);
  assert.match(content,/No allocation was committed/);
});

package simu.manufacturing;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import static org.junit.jupiter.api.Assertions.*;
import java.util.*;
@EnabledIfEnvironmentVariable(named="MANUFACTURING_TEST_DATABASE",matches=".+")
class ControllerTest {
 @Test void gracefulStandaloneShutdownPreservesHeldRunForRestart()throws Exception{
  var settings=new Settings(Map.of("DATABASE_URL",System.getenv("MANUFACTURING_TEST_DATABASE"),"APP_PASSWORD","test","AUTONOMOUS_SAMPLE","false"));var store=new Store(settings);Thread task=null;
  try{store.migrate();store.control("reset",1,store.run().get("id").toString(),null,null);store.control("hold",1,null,null,null);task=new Thread(()->new Controller(store,settings).run());task.start();boolean owned=false;
   for(int i=0;i<60&&!owned;i++){owned=store.tx(c->!Boolean.TRUE.equals(Store.one(c,"SELECT pg_try_advisory_xact_lock(8192102) held").get("held")));if(!owned)Thread.sleep(50);}assertTrue(owned);task.interrupt();task.join(5000);assertFalse(task.isAlive());assertEquals("held",store.run().get("state"));
  }finally{if(task!=null){task.interrupt();task.join(5000);}store.pool.close();}
 }
 @Test void resetBetweenPrepareAndLocalGrantLeavesNewRunUsable(){
  var settings=new Settings(Map.of("DATABASE_URL",System.getenv("MANUFACTURING_TEST_DATABASE"),"APP_PASSWORD","test"));var store=new Store(settings);
  try{store.migrate();store.control("reset",1,store.run().get("id").toString(),null,null);var prior=store.run();assertTrue(store.prepare(1,prior.get("epoch")));
   store.control("reset",1,prior.get("id").toString(),null,null);var next=store.run();
   assertFalse(new Controller(store,settings).grantLocal(1,prior.get("epoch")));assertEquals(next.get("id"),store.run().get("id"));assertEquals("running",store.run().get("state"));assertEquals(0,Store.number(store.run(),"granted"));
   assertTrue(store.prepare(1,next.get("epoch")));assertTrue(new Controller(store,settings).grantLocal(1,next.get("epoch")));assertEquals(1,Store.number(store.run(),"granted"));
  }finally{store.pool.close();}
 }
 @Test void standaloneLeaseLossPreservesRunAndReacquiresController()throws Exception{
  var settings=new Settings(Map.of("DATABASE_URL",System.getenv("MANUFACTURING_TEST_DATABASE"),"APP_PASSWORD","test","AUTONOMOUS_SAMPLE","false"));var store=new Store(settings);Thread task=null;
  try{store.migrate();store.control("reset",1,store.run().get("id").toString(),null,null);store.control("hold",1,null,null,null);var initial=store.run();task=new Thread(()->new Controller(store,settings).run());task.start();
   Integer original=null;for(int i=0;i<100&&original==null;i++){original=controllerPid(store);if(original==null)Thread.sleep(50);}assertNotNull(original);int pid=original;
   store.tx(c->Store.one(c,"SELECT pg_terminate_backend(?)",pid));Integer next=null;
   for(int i=0;i<100;i++){next=controllerPid(store);if(next!=null&&!next.equals(original))break;Thread.sleep(50);}
   assertEquals("held",store.run().get("state"));assertEquals(initial.get("id"),store.run().get("id"));assertEquals(initial.get("epoch"),store.run().get("epoch"));assertNotNull(next);assertNotEquals(original,next);assertTrue(task.isAlive());
  }finally{if(task!=null){task.interrupt();task.join(5000);}store.pool.close();}
 }
 private static Integer controllerPid(Store store){return store.tx(c->{var row=Store.one(c,"SELECT pid FROM pg_locks WHERE locktype='advisory' AND classid=0 AND objid=8192102 AND granted AND database=(SELECT oid FROM pg_database WHERE datname=current_database()) LIMIT 1");return row==null?null:((Number)row.get("pid")).intValue();});}
}

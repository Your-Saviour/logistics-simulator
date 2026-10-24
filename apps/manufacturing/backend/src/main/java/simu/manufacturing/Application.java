package simu.manufacturing;
import org.springframework.boot.*;
import org.springframework.boot.autoconfigure.*;
import org.springframework.context.annotation.Bean;
@SpringBootApplication
public class Application {
 public static void main(String[] args){SpringApplication.run(Application.class,args);}
 @Bean Settings settings(){return new Settings(System.getenv());}
 @Bean Store store(Settings settings){var store=new Store(settings);store.migrate();return store;}
 @Bean ApplicationRunner roles(Store store,Settings settings){return args->{
  if(settings.role.equals("worker")||settings.role.equals("controller")){
   var task=new Thread(()->{if(settings.role.equals("worker"))Messaging.worker(store,settings);else new Controller(store,settings).run();},"manufacturing-"+settings.role);task.setDaemon(false);Runtime.getRuntime().addShutdownHook(new Thread(task::interrupt));task.start();
  }
 };}
}

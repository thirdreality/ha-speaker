
#include <mutex>
#include <condition_variable>

#include "3r_ledring_binding.h"

using namespace std;

static void handle_method_call(GDBusConnection       *connection,
    const gchar           *sender,
    const gchar           *object_path,
    const gchar           *interface_name,
    const gchar           *method_name,
    GVariant              *parameters,
    GDBusMethodInvocation *invocation,
    gpointer               user_data)
{
    g_print("handle_method_call(). sender: %s, object_path: %s, interface_name: %s, method_name: %s\n", sender, object_path, interface_name, method_name);
    if (g_strcmp0(method_name, "FactoryReset") == 0) {
        gchar *response;
        response = g_strdup_printf("True");
        g_dbus_method_invocation_return_value(invocation,
            g_variant_new("(s)", response));
        g_free(response);
    }
}

static const GDBusInterfaceVTable interface_vtable =
{
    handle_method_call,
};

//extern mutex led_command_mutex;
//extern condition_variable led_command_cond;
void set_new_animations(GVariant *parameters);

static void on_lcd_show(GDBusConnection *connection,
    const gchar     *sender,
    const gchar     *object_path,
    const gchar     *interface_name,
    const gchar     *signal_name,
    GVariant        *parameters,
    gpointer         user_data)
{
	// g_print("sender: %s, object_path: %s, interface_name: %s, signal_name: %s\n", sender, object_path, interface_name, signal_name);
	// g_print("parameters: %s\n", g_variant_print(parameters, TRUE));

	set_new_animations(parameters);
}

static guint registration_id = -1;
static guint signal_id = -1;
static void on_bus_acquired (GDBusConnection *connection,
                 const gchar     *name,
                 gpointer         user_data)
{
    GError *error;

    registration_id = g_dbus_connection_register_object(connection,
        "/com/3r/EventBus",
        com_3reality_event_bus_interface_info(),
        &interface_vtable,
        NULL,  /* user_data */
        NULL,  /* user_data_free_func */
        NULL); /* GError** */
    g_assert(registration_id > 0);

    signal_id = g_dbus_connection_signal_subscribe(connection,
        NULL, /* sender */
        "com._3reality.EventBus", /* interface_name */
        "LedShow", /* member */
        "/com/3r/EventBus", /* object_path */
        NULL, /* arg0 */
        G_DBUS_SIGNAL_FLAGS_NONE,
		on_lcd_show,
        NULL,  /* user_data */
        NULL); /* user_data_free_func */
}

static void on_name_acquired (GDBusConnection *connection,
                  const gchar     *name,
                  gpointer         user_data)
{
//   INFO ("Acquired the name %s\n", name);
}

static void on_name_lost (GDBusConnection *connection,
              const gchar     *name,
              gpointer         user_data)
{
//   WARN ("Lost the name %s\n", name);

  if (signal_id != -1) {
      g_dbus_connection_signal_unsubscribe(connection, signal_id);
      signal_id = -1;
  }
  if (registration_id != -1) {
      g_assert(g_dbus_connection_unregister_object(connection, registration_id));
      registration_id = -1;
  }

}

static void* extern_event_handle(void* arg)
{
  GMainLoop *loop;
  guint id;

//   DBG("[3r_ledring] using system dbus...\n");
  id = g_bus_own_name (G_BUS_TYPE_SYSTEM,
                       "com._3reality.Ledring",
                       (GBusNameOwnerFlags )(G_BUS_NAME_OWNER_FLAGS_ALLOW_REPLACEMENT | G_BUS_NAME_OWNER_FLAGS_REPLACE),
                       on_bus_acquired,
                       on_name_acquired,
                       on_name_lost,
                       loop,
                       NULL);

  loop = g_main_loop_new(NULL, FALSE);
  g_main_loop_run (loop);

  g_bus_unown_name (id);
  g_main_loop_unref (loop);

  return NULL;
}

static pthread_t extern_event_task_id;
void extern_event_task_init()
{
	pthread_create(&extern_event_task_id, NULL, extern_event_handle, NULL);
}
